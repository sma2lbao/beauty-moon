"""Component-differentiated health check."""
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import create_app


def test_health_all_up():
    with patch("app.db.vectorstore.get_vector_store"), patch(
        "app.services.llm.check_ark_health", return_value=True
    ), patch("app.services.llm.check_ollama_health", return_value=True):
        client = TestClient(create_app())
        resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["components"]["database"]["status"] == "up"
    assert "latency_ms" in body["components"]["database"]


def test_health_degraded_when_vectorstore_down():
    with patch(
        "app.db.vectorstore.get_vector_store", side_effect=RuntimeError("boom")
    ):
        client = TestClient(create_app())
        resp = client.get("/api/v1/health")
    body = resp.json()
    assert resp.status_code == 200
    assert body["status"] == "degraded"
    assert body["components"]["vectorstore"]["status"] == "down"


def test_health_llm_provider_component_reflects_configured_only():
    with patch("app.db.vectorstore.get_vector_store"):
        client = TestClient(create_app())
        resp = client.get("/api/v1/health")
    body = resp.json()
    assert "provider" in body["components"]["llm_provider"]
