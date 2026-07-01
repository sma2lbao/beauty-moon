"""/metrics endpoint behavior."""
from fastapi.testclient import TestClient

from app.main import create_app
from app.security.middleware import _RATE_LIMIT_EXEMPT


def test_metrics_endpoint_exposes_prometheus():
    client = TestClient(create_app())
    resp = client.get("/metrics")
    assert resp.status_code == 200
    assert "text/plain" in resp.headers["content-type"]
    assert "http_requests_total" in resp.text


def test_metrics_endpoint_exempt_from_rate_limit():
    assert "/metrics" in _RATE_LIMIT_EXEMPT


def test_metrics_disabled_returns_404(monkeypatch):
    from app.core import config

    monkeypatch.setattr(
        config.get_settings(), "metrics_enabled", False, raising=False
    )
    client = TestClient(create_app())
    resp = client.get("/metrics")
    assert resp.status_code == 404
