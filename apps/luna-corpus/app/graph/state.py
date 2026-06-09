"""LangGraph state definitions."""
import operator
from typing import Annotated

from typing_extensions import TypedDict


class RAGState(TypedDict):
    """State for RAG question-answering graph."""

    question: str
    retrieved_docs: Annotated[list[dict], operator.add]
    answer: str | None
    sources: list[dict]
    processing_time_ms: int | None


class DocumentProcessingState(TypedDict):
    """State for document processing graph."""

    document_id: str
    status: str
    chunks_created: int
    error: str | None
