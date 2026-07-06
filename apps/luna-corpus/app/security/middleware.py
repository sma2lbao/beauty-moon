"""ASGI middleware: request context, rate limiting, body-size limits."""
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.config import get_settings
from app.security.context import reset_request_context, set_request_context
from app.security.rate_limiter import RateLimiter

# Live routes are mounted under this API prefix (see routes.py APIRouter).
_API_PREFIX = "/api/v1"
_RATE_LIMIT_EXEMPT = {"/", "/health", "/metrics", f"{_API_PREFIX}/health"}


def _strip_api_prefix(path: str) -> str:
    """Remove the API router prefix so category matching is prefix-agnostic."""
    if path.startswith(_API_PREFIX):
        return path[len(_API_PREFIX) :] or "/"
    return path


def resolve_category(path: str) -> str:
    """Map a request path to a rate-limit category."""
    path = _strip_api_prefix(path)
    if path.startswith("/qa/"):
        return "qa"
    if path == "/files/upload" or (
        path.startswith("/documents/") and path.endswith("/process")
    ):
        return "upload"
    return "default"


def _client_ip(request: Request) -> str | None:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Generate/propagate request_id and capture client IP."""

    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = request.headers.get("X-Request-Id") or str(uuid.uuid4())
        set_request_context(request_id, _client_ip(request))
        try:
            response = await call_next(request)
        finally:
            reset_request_context()
        response.headers["X-Request-Id"] = request_id
        return response


class BodySizeLimitMiddleware(BaseHTTPMiddleware):
    """Reject oversized non-multipart request bodies with 413."""

    def __init__(self, app, max_body_size: int | None = None) -> None:
        super().__init__(app)
        self._max_body_size = max_body_size

    async def dispatch(self, request: Request, call_next) -> Response:
        max_size = (
            self._max_body_size
            if self._max_body_size is not None
            else get_settings().max_json_body_size
        )
        content_type = request.headers.get("content-type", "")
        if not content_type.startswith("multipart/"):
            # Pre-check the declared Content-Length before buffering the body,
            # so oversized payloads are rejected without being read into memory.
            content_length = request.headers.get("content-length")
            if content_length is not None:
                try:
                    if int(content_length) > max_size:
                        return JSONResponse(
                            status_code=413,
                            content={"detail": "Request body too large"},
                        )
                except ValueError:
                    pass
            body = await request.body()
            if len(body) > max_size:
                return JSONResponse(
                    status_code=413,
                    content={"detail": "Request body too large"},
                )
        return await call_next(request)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Per-identity, per-category fixed-window rate limiting."""

    def __init__(self, app, limiter: RateLimiter | None = None) -> None:
        super().__init__(app)
        self._limiter = limiter or RateLimiter()

    async def dispatch(self, request: Request, call_next) -> Response:
        settings = get_settings()
        if not settings.rate_limit_enabled or request.url.path in _RATE_LIMIT_EXEMPT:
            return await call_next(request)

        category = resolve_category(request.url.path)
        limit = {
            "qa": settings.rate_limit_qa_per_minute,
            "upload": settings.rate_limit_upload_per_minute,
        }.get(category, settings.rate_limit_default_per_minute)

        identity = request.headers.get("X-User-Id") or (
            request.client.host if request.client else "anonymous"
        )
        key = f"{identity}:{category}"
        if not self._limiter.check(key, limit):
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded"},
                headers={"Retry-After": "60"},
            )
        return await call_next(request)
