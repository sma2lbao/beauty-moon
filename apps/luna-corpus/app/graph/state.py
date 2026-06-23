"""LangGraph state definitions."""
import operator
from typing import Annotated

from typing_extensions import TypedDict


class MessageDict(TypedDict):
    """Message dictionary structure."""

    id: str
    role: str
    content: str
    created_at: str


class RAGState(TypedDict):
    """State for RAG question-answering graph."""

    question: str
    knowledge_base_id: str | None
    conversation_id: str | None
    conversation_history: list[MessageDict]
    retrieved_docs: Annotated[list[dict], operator.add]
    answer: str | None
    sources: list[dict]
    processing_time_ms: int | None
    needs_summarization: bool


class DocumentProcessingState(TypedDict):
    """State for document processing graph."""

    document_id: str
    status: str
    chunks_created: int
    error: str | None
