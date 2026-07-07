"""Tests for rerank-related settings."""
from app.core.config import RerankProvider, RetrievalMode, Settings


def test_retrieval_mode_has_rerank():
    assert RetrievalMode.RERANK == "rerank"


def test_rerank_provider_default_is_bge():
    settings = Settings()
    assert settings.reranker_provider == RerankProvider.BGE


def test_rerank_defaults():
    settings = Settings()
    assert settings.rerank_model == "BAAI/bge-reranker-v2-m3"
    assert settings.rerank_candidate_k == 20
    assert settings.rerank_batch_size == 32
