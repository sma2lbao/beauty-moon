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
RAG_RERANK_DURATION = Histogram(
    "rag_rerank_duration_seconds",
    "Rerank (cross-encoder) latency in seconds.",
)
RAG_FACET_DURATION = Histogram(
    "rag_facet_duration_seconds",
    "Facet aggregation latency in seconds.",
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

QA_INTERACTIONS_TOTAL = Counter(
    "qa_interactions_total",
    "Total recorded Q&A interactions",
)
QA_FEEDBACK_TOTAL = Counter(
    "qa_feedback_total",
    "Total user feedback submissions",
    ["rating"],
)
QA_EVALUATIONS_TOTAL = Counter(
    "qa_evaluations_total",
    "Total LLM quality evaluations by terminal status",
    ["status"],
)
LLM_TOKENS_TOTAL = Counter(
    "llm_tokens_total",
    "Total LLM tokens consumed by direction.",
    ["provider", "model", "direction"],
)
LLM_COST_TOTAL = Counter(
    "llm_cost_total",
    "Total LLM cost in currency units.",
    ["provider", "model", "currency"],
)
QUOTA_REJECTED_TOTAL = Counter(
    "quota_rejected_total",
    "Total requests rejected by quota enforcement.",
    ["scope_type"],
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
