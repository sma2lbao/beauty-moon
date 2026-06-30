"""Tests for security middleware: request context, rate limit, body size."""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.security.middleware import (
    BodySizeLimitMiddleware,
    RateLimitMiddleware,
    RequestContextMiddleware,
    resolve_category,
)
from app.security.rate_limiter import RateLimiter


def _build_app(limiter: RateLimiter, max_body: int = 1048576) -> FastAPI:
    app = FastAPI()
    app.add_middleware(RateLimitMiddleware, limiter=limiter)
    app.add_middleware(BodySizeLimitMiddleware, max_body_size=max_body)
    app.add_middleware(RequestContextMiddleware)

    @app.post("/qa/query")
    async def qa():
        return {"ok": True}

    @app.get("/")
    async def root():
        return {"ok": True}

    return app


def test_resolve_category():
    assert resolve_category("/qa/query") == "qa"
    assert resolve_category("/qa/stream") == "qa"
    assert resolve_category("/files/upload") == "upload"
    assert resolve_category("/documents/abc/process") == "upload"
    assert resolve_category("/documents") == "default"


def test_request_id_generated_and_returned():
    client = TestClient(_build_app(RateLimiter()))
    resp = client.get("/")
    assert resp.status_code == 200
    assert resp.headers.get("X-Request-Id")


def test_request_id_honored_from_header():
    client = TestClient(_build_app(RateLimiter()))
    resp = client.get("/", headers={"X-Request-Id": "incoming-123"})
    assert resp.headers["X-Request-Id"] == "incoming-123"


def test_rate_limit_returns_429_with_retry_after():
    # qa category limit comes from settings; force a tiny limit via many calls.
    from app.core.config import get_settings

    limiter = RateLimiter()
    client = TestClient(_build_app(limiter))
    limit = get_settings().rate_limit_qa_per_minute
    last = None
    for _ in range(limit + 1):
        last = client.post("/qa/query")
    assert last.status_code == 429
    assert last.headers["Retry-After"] == "60"


def test_root_path_not_rate_limited():
    limiter = RateLimiter()
    client = TestClient(_build_app(limiter))
    for _ in range(200):
        resp = client.get("/")
    assert resp.status_code == 200


def test_body_size_limit_returns_413():
    client = TestClient(_build_app(RateLimiter(), max_body=10))
    resp = client.post("/qa/query", content=b"x" * 50)
    assert resp.status_code == 413
