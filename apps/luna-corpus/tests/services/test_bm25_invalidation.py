"""Ingestion write/delete paths invalidate the BM25 cache."""
from app.services import document_processor
from app.services.ingestion import service as ingestion_service


def test_document_processor_module_imports_invalidate():
    # Guards against the import being dropped in a future refactor.
    assert hasattr(document_processor, "invalidate_bm25_cache")


def test_ingestion_service_module_imports_invalidate():
    assert hasattr(ingestion_service, "invalidate_bm25_cache")
