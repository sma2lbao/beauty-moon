"""Prometheus metric definitions and a timing context manager."""
import time
from contextlib import contextmanager

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Histogram,
    generate_latest,
)

HTTP_REQUESTS_TOTAL = Counter(
    "http_requests_total",
    "Total HTTP requests.",
    ["method", "path_template", "status"],
)
HTTP_REQUEST_DURATION = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency in seconds.",
    ["method", "path_template"],
)
RAG_RETRIEVAL_DURATION = Histogram(
    "rag_retrieval_duration_seconds",
    "Vector retrieval latency in seconds.",
)
LLM_GENERATION_DURATION = Histogram(
    "llm_generation_duration_seconds",
    "LLM generation latency in seconds.",
    ["provider"],
)
EMBEDDING_DURATION = Histogram(
    "embedding_duration_seconds",
    "Embedding latency in seconds.",
    ["provider"],
)
INDEX_TASK_DURATION = Histogram(
    "index_task_duration_seconds",
    "Index task duration in seconds.",
    ["result"],
)


@contextmanager
def time_stage(histogram, **labels):
    """Observe elapsed seconds into `histogram`, even on exception."""
    start = time.perf_counter()
    try:
        yield
    finally:
        elapsed = time.perf_counter() - start
        target = histogram.labels(**labels) if labels else histogram
        target.observe(elapsed)


def render_metrics() -> tuple[bytes, str]:
    """Return the Prometheus exposition payload and content type."""
    return generate_latest(), CONTENT_TYPE_LATEST
