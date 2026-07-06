"""HTTP metrics + access-log middleware."""
import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.config import get_settings
from app.observability.logging import get_logger
from app.observability.metrics import HTTP_REQUEST_DURATION, HTTP_REQUESTS_TOTAL

_logger = get_logger("luna.access")


def resolve_path_template(request: Request) -> str:
    """Return the matched route template, or 'unmatched'."""
    route = request.scope.get("route")
    if route is not None and getattr(route, "path", None):
        return route.path
    return "unmatched"


class MetricsMiddleware(BaseHTTPMiddleware):
    """Record request count/duration and emit a structured access log."""

    async def dispatch(self, request: Request, call_next) -> Response:
        if not get_settings().metrics_enabled:
            return await call_next(request)

        start = time.perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        finally:
            elapsed = time.perf_counter() - start
            template = resolve_path_template(request)
            method = request.method
            try:
                HTTP_REQUESTS_TOTAL.labels(
                    method=method,
                    path_template=template,
                    status=str(status_code),
                ).inc()
                HTTP_REQUEST_DURATION.labels(
                    method=method, path_template=template
                ).observe(elapsed)
                _logger.info(
                    "request_completed",
                    method=method,
                    path=template,
                    status=status_code,
                    latency_ms=round(elapsed * 1000, 2),
                )
            except Exception:  # observability must never break the request
                pass
