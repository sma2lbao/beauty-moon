"""API routes for luna-corpus."""
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import Chunk, ContentStatus, Document
from app.graph.rag_graph import answer_question
from app.services.document_processor import DocumentProcessor

router = APIRouter(prefix="/api/v1", tags=["qa"])


# Request/Response Models
class QuestionRequest(BaseModel):
    """Question request model."""

    question: str = Field(..., min_length=1, max_length=1000)
    top_k: int = Field(default=5, ge=1, le=20)


class SourceResponse(BaseModel):
    """Source reference model."""

    document_id: str
    document_title: str | None = None
    chunk_content: str
    relevance_score: float


class AnswerResponse(BaseModel):
    """Answer response model."""

    answer: str
    sources: list[SourceResponse]
    processing_time_ms: int


class DocumentCreate(BaseModel):
    """Document creation model."""

    title: str = Field(..., min_length=1, max_length=500)
    content: str = Field(..., min_length=1)
    source: str | None = None


class DocumentResponse(BaseModel):
    """Document response model."""

    id: str
    title: str
    source: str | None
    content: str
    has_tables: bool
    has_code: bool
    status: str
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True


class DocumentListResponse(BaseModel):
    """Document list response."""

    documents: list[DocumentResponse]
    total: int


class HealthResponse(BaseModel):
    """Health check response."""

    status: str
    mysql: str
    chroma: str
    ollama: str


class ProcessResponse(BaseModel):
    """Document processing response."""

    status: str
    chunks_created: int


# Question Answering
@router.post("/qa/query", response_model=AnswerResponse)
async def query(question_req: QuestionRequest) -> AnswerResponse:
    """Answer a question using RAG.

    Args:
        question_req: Question request

    Returns:
        Answer with sources
    """
    result = answer_question(question_req.question)

    # Enrich sources with document titles
    enriched_sources = []
    for source in result["sources"]:
        enriched_sources.append(
            SourceResponse(
                document_id=source["document_id"],
                chunk_content=source["chunk_content"],
                relevance_score=source["relevance_score"],
            )
        )

    return AnswerResponse(
        answer=result["answer"],
        sources=enriched_sources,
        processing_time_ms=result["processing_time_ms"],
    )


# Document Management
@router.post("/documents", response_model=DocumentResponse, status_code=status.HTTP_201_CREATED)
async def create_document(
    doc: DocumentCreate,
    db: Annotated[Session, Depends(get_db)],
) -> DocumentResponse:
    """Create a new document.

    Args:
        doc: Document to create
        db: Database session

    Returns:
        Created document
    """
    db_doc = Document(
        title=doc.title,
        content=doc.content,
        source=doc.source,
        has_tables="|" in doc.content and "---" in doc.content,
        has_code="```" in doc.content or "def " in doc.content,
    )
    db.add(db_doc)
    db.commit()
    db.refresh(db_doc)

    return DocumentResponse(
        id=db_doc.id,
        title=db_doc.title,
        source=db_doc.source,
        content=db_doc.content,
        has_tables=db_doc.has_tables,
        has_code=db_doc.has_code,
        status=db_doc.status.value,
        created_at=db_doc.created_at.isoformat(),
        updated_at=db_doc.updated_at.isoformat(),
    )


@router.get("/documents", response_model=DocumentListResponse)
async def list_documents(
    db: Annotated[Session, Depends(get_db)],
    status_filter: ContentStatus | None = None,
) -> DocumentListResponse:
    """List all documents.

    Args:
        db: Database session
        status_filter: Optional status filter

    Returns:
        List of documents
    """
    query = db.query(Document)

    if status_filter:
        query = query.filter(Document.status == status_filter)

    documents = query.order_by(Document.created_at.desc()).all()

    return DocumentListResponse(
        documents=[
            DocumentResponse(
                id=doc.id,
                title=doc.title,
                source=doc.source,
                content=doc.content,
                has_tables=doc.has_tables,
                has_code=doc.has_code,
                status=doc.status.value,
                created_at=doc.created_at.isoformat(),
                updated_at=doc.updated_at.isoformat(),
            )
            for doc in documents
        ],
        total=len(documents),
    )


@router.get("/documents/{document_id}", response_model=DocumentResponse)
async def get_document(
    document_id: str,
    db: Annotated[Session, Depends(get_db)],
) -> DocumentResponse:
    """Get a document by ID.

    Args:
        document_id: Document ID
        db: Database session

    Returns:
        Document
    """
    doc = db.query(Document).filter(Document.id == document_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    return DocumentResponse(
        id=doc.id,
        title=doc.title,
        source=doc.source,
        content=doc.content,
        has_tables=doc.has_tables,
        has_code=doc.has_code,
        status=doc.status.value,
        created_at=doc.created_at.isoformat(),
        updated_at=doc.updated_at.isoformat(),
    )


@router.delete("/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    document_id: str,
    db: Annotated[Session, Depends(get_db)],
) -> None:
    """Delete a document.

    Args:
        document_id: Document ID
        db: Database session
    """
    doc = db.query(Document).filter(Document.id == document_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    db.delete(doc)
    db.commit()


@router.post("/documents/{document_id}/process", response_model=ProcessResponse)
async def process_document(
    document_id: str,
    db: Annotated[Session, Depends(get_db)],
) -> ProcessResponse:
    """Process a document: chunk and vectorize.

    Args:
        document_id: Document ID
        db: Database session

    Returns:
        Processing result
    """
    doc = db.query(Document).filter(Document.id == document_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    processor = DocumentProcessor()
    chunks = processor.process_document(db, document_id)

    return ProcessResponse(
        status="completed",
        chunks_created=len(chunks),
    )


# Health Check
@router.get("/health", response_model=HealthResponse)
async def health_check(db: Annotated[Session, Depends(get_db)]) -> HealthResponse:
    """Check system health.

    Args:
        db: Database session

    Returns:
        Health status
    """
    from app.db.vectorstore import get_vector_store
    from app.services.llm import check_ollama_health

    # Check MySQL
    mysql_status = "connected"
    try:
        db.execute("SELECT 1")
    except Exception:
        mysql_status = "error"

    # Check Chroma
    chroma_status = "connected"
    try:
        get_vector_store()
    except Exception:
        chroma_status = "error"

    # Check Ollama
    ollama_status = "connected" if check_ollama_health() else "disconnected"

    overall_status = "ok"
    if mysql_status != "connected" or chroma_status != "connected":
        overall_status = "degraded"

    return HealthResponse(
        status=overall_status,
        mysql=mysql_status,
        chroma=chroma_status,
        ollama=ollama_status,
    )
