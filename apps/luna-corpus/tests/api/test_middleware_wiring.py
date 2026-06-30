"""Verify security middleware is wired into the app."""
from app.main import create_app
from app.security.middleware import (
    BodySizeLimitMiddleware,
    RateLimitMiddleware,
    RequestContextMiddleware,
)


def test_security_middleware_registered():
    app = create_app()
    classes = {m.cls for m in app.user_middleware}
    assert RequestContextMiddleware in classes
    assert RateLimitMiddleware in classes
    assert BodySizeLimitMiddleware in classes


def test_request_id_header_present_on_root():
    from fastapi.testclient import TestClient

    client = TestClient(create_app())
    resp = client.get("/")
    assert resp.headers.get("X-Request-Id")
