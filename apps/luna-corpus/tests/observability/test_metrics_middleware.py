"""MetricsMiddleware records counts, durations, and access logs."""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.observability.metrics import HTTP_REQUESTS_TOTAL
from app.observability.middleware import MetricsMiddleware


def _build_app():
    app = FastAPI()
    app.add_middleware(MetricsMiddleware)

    @app.get("/items/{item_id}")
    async def item(item_id: str):
        return {"id": item_id}

    return app


def test_request_counted_with_path_template():
    client = TestClient(_build_app())
    before = HTTP_REQUESTS_TOTAL.labels(
        method="GET", path_template="/items/{item_id}", status="200"
    )._value.get()
    client.get("/items/abc")
    client.get("/items/xyz")
    after = HTTP_REQUESTS_TOTAL.labels(
        method="GET", path_template="/items/{item_id}", status="200"
    )._value.get()
    # Both distinct paths collapse into one templated series.
    assert after - before == 2


def test_unmatched_route_labeled_unmatched():
    client = TestClient(_build_app())
    before = HTTP_REQUESTS_TOTAL.labels(
        method="GET", path_template="unmatched", status="404"
    )._value.get()
    client.get("/nope")
    after = HTTP_REQUESTS_TOTAL.labels(
        method="GET", path_template="unmatched", status="404"
    )._value.get()
    assert after - before == 1
