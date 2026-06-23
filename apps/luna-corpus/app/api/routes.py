"""API routes for luna-corpus."""
import json
import time
from datetime import datetime
from typing import Annotated, AsyncGenerator

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.api.context import RequestContext, require_request_context
from app.db.database import get_db
from app.db.models import Chunk, ContentStatus, Conversation, Document, Message, MessageRole
from app.graph.rag_graph import (
    answer_question,
    answer_question_multi_turn,
    answer_question_multi_turn_stream,
    answer_question_stream,
)
from app.services.document_processor import DocumentProcessor
from app.services.memory import (
    add_message_to_conversation,
    create_conversation,
    delete_conversation as memory_delete_conversation,
    clear_conversation_messages,
    get_conversation,
    get_message_count,
)

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

    model_config = ConfigDict(from_attributes=True)


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
    ark: str
    llm_provider: str


class ProcessResponse(BaseModel):
    """Document processing response."""

    status: str
    chunks_created: int


# Conversation Models
class ConversationCreate(BaseModel):
    """Conversation creation model."""

    title: str | None = Field(default=None, max_length=255)


class ConversationResponse(BaseModel):
    """Conversation response model."""

    id: str
    title: str | None
    is_active: bool
    summary: str | None
    created_at: str
    updated_at: str
    message_count: int = 0

    model_config = ConfigDict(from_attributes=True)


class ConversationListResponse(BaseModel):
    """Conversation list response."""

    conversations: list[ConversationResponse]
    total: int


class MessageResponse(BaseModel):
    """Message response model."""

    id: str
    conversation_id: str
    role: str
    content: str
    created_at: str

    model_config = ConfigDict(from_attributes=True)


class MultiTurnQuestionRequest(BaseModel):
    """Multi-turn question request with conversation context."""

    question: str = Field(..., min_length=1, max_length=2000)
    conversation_id: str | None = Field(default=None, description="Existing conversation ID")
    include_history: bool = Field(default=True, description="Include conversation history")


class MultiTurnAnswerResponse(BaseModel):
    """Multi-turn answer response."""

    answer: str
    conversation_id: str
    sources: list[SourceResponse]
    processing_time_ms: int


# Question Answering
@router.post("/qa/query", response_model=AnswerResponse)
async def query(
    question_req: QuestionRequest,
    context: Annotated[RequestContext, Depends(require_request_context)],
) -> AnswerResponse:
    """Answer a question using RAG.

    Args:
        question_req: Question request
        context: Request context with knowledge base scope

    Returns:
        Answer with sources
    """
    result = answer_question(question_req.question, context.knowledge_base.id)

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


async def stream_event_generator(question: str, knowledge_base_id: str) -> AsyncGenerator[str, None]:
    """Generate SSE events for streaming answer.

    Args:
        question: User question
        knowledge_base_id: Knowledge base ID for retrieval filtering

    Yields:
        SSE formatted event strings
    """
    try:
        async for event in answer_question_stream(question, knowledge_base_id):
            yield f"data: {json.dumps(event)}\n\n"
    except Exception as e:
        yield f"data: {json.dumps({'event': 'error', 'data': str(e)})}\n\n"


@router.post("/qa/stream")
async def stream_query(
    question_req: QuestionRequest,
    context: Annotated[RequestContext, Depends(require_request_context)],
):
    """Stream answer to a question using RAG.

    Args:
        question_req: Question request
        context: Request context with knowledge base scope

    Returns:
        StreamingResponse with SSE events
    """
    return StreamingResponse(
        stream_event_generator(question_req.question, context.knowledge_base.id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# Document Management
@router.post("/documents", response_model=DocumentResponse, status_code=status.HTTP_201_CREATED)
async def create_document(
    doc: DocumentCreate,
    db: Annotated[Session, Depends(get_db)],
    context: Annotated[RequestContext, Depends(require_request_context)],
) -> DocumentResponse:
    """Create a new document.

    Args:
        doc: Document to create
        db: Database session
        context: Request context with knowledge base scope

    Returns:
        Created document
    """
    db_doc = Document(
        title=doc.title,
        content=doc.content,
        source=doc.source,
        has_tables="|" in doc.content and "---" in doc.content,
        has_code="```" in doc.content or "def " in doc.content,
        knowledge_base_id=context.knowledge_base.id,
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
    context: Annotated[RequestContext, Depends(require_request_context)],
    status_filter: ContentStatus | None = None,
) -> DocumentListResponse:
    """List all documents.

    Args:
        db: Database session
        context: Request context with knowledge base scope
        status_filter: Optional status filter

    Returns:
        List of documents
    """
    query = db.query(Document).filter(
        Document.knowledge_base_id == context.knowledge_base.id
    )

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
    context: Annotated[RequestContext, Depends(require_request_context)],
) -> DocumentResponse:
    """Get a document by ID.

    Args:
        document_id: Document ID
        db: Database session
        context: Request context with knowledge base scope

    Returns:
        Document
    """
    doc = (
        db.query(Document)
        .filter(
            Document.id == document_id,
            Document.knowledge_base_id == context.knowledge_base.id,
        )
        .first()
    )
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
    context: Annotated[RequestContext, Depends(require_request_context)],
) -> None:
    """Delete a document.

    Args:
        document_id: Document ID
        db: Database session
        context: Request context with knowledge base scope
    """
    doc = (
        db.query(Document)
        .filter(
            Document.id == document_id,
            Document.knowledge_base_id == context.knowledge_base.id,
        )
        .first()
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    db.delete(doc)
    db.commit()


@router.post("/documents/{document_id}/process", response_model=ProcessResponse)
async def process_document(
    document_id: str,
    db: Annotated[Session, Depends(get_db)],
    context: Annotated[RequestContext, Depends(require_request_context)],
) -> ProcessResponse:
    """Process a document: chunk and vectorize.

    Args:
        document_id: Document ID
        db: Database session
        context: Request context with knowledge base scope

    Returns:
        Processing result
    """
    doc = (
        db.query(Document)
        .filter(
            Document.id == document_id,
            Document.knowledge_base_id == context.knowledge_base.id,
        )
        .first()
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    processor = DocumentProcessor()
    chunks = processor.process_document(db, document_id)

    return ProcessResponse(
        status="completed",
        chunks_created=len(chunks),
    )


# Conversation Management
@router.post("/conversations", response_model=ConversationResponse, status_code=status.HTTP_201_CREATED)
async def create_conversation_endpoint(
    conv: ConversationCreate,
    db: Annotated[Session, Depends(get_db)],
) -> ConversationResponse:
    """Create a new conversation.

    Args:
        conv: Conversation data
        db: Database session

    Returns:
        Created conversation
    """
    db_conv = create_conversation(db, conv.title)

    return ConversationResponse(
        id=db_conv.id,
        title=db_conv.title,
        is_active=db_conv.is_active,
        summary=db_conv.summary,
        created_at=db_conv.created_at.isoformat(),
        updated_at=db_conv.updated_at.isoformat(),
        message_count=0,
    )


@router.get("/conversations", response_model=ConversationListResponse)
async def list_conversations(
    db: Annotated[Session, Depends(get_db)],
    active_only: bool = Query(default=True),
    limit: int = Query(default=50, ge=1, le=100),
) -> ConversationListResponse:
    """List all conversations.

    Args:
        db: Database session
        active_only: Filter to active conversations only
        limit: Maximum number to return

    Returns:
        List of conversations
    """
    # Subquery to count messages per conversation
    message_count_subq = (
        db.query(
            Message.conversation_id,
            func.count(Message.id).label("message_count"),
        )
        .group_by(Message.conversation_id)
        .subquery()
    )

    # Main query with LEFT JOIN to message counts
    query = db.query(Conversation, message_count_subq.c.message_count).outerjoin(
        message_count_subq,
        Conversation.id == message_count_subq.c.conversation_id,
    )

    if active_only:
        query = query.filter(Conversation.is_active == True)

    results = query.order_by(Conversation.updated_at.desc()).limit(limit).all()

    conversations_response = []
    for conv, message_count in results:
        conversations_response.append(ConversationResponse(
            id=conv.id,
            title=conv.title,
            is_active=conv.is_active,
            summary=conv.summary,
            created_at=conv.created_at.isoformat(),
            updated_at=conv.updated_at.isoformat(),
            message_count=message_count or 0,
        ))

    return ConversationListResponse(
        conversations=conversations_response,
        total=len(conversations_response),
    )


@router.get("/conversations/{conversation_id}", response_model=ConversationResponse)
async def get_conversation_endpoint(
    conversation_id: str,
    db: Annotated[Session, Depends(get_db)],
) -> ConversationResponse:
    """Get a conversation by ID.

    Args:
        conversation_id: Conversation ID
        db: Database session

    Returns:
        Conversation
    """
    conv = get_conversation(db, conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    message_count = get_message_count(db, conversation_id)

    return ConversationResponse(
        id=conv.id,
        title=conv.title,
        is_active=conv.is_active,
        summary=conv.summary,
        created_at=conv.created_at.isoformat(),
        updated_at=conv.updated_at.isoformat(),
        message_count=message_count,
    )


@router.get("/conversations/{conversation_id}/messages", response_model=list[MessageResponse])
async def get_conversation_messages_endpoint(
    conversation_id: str,
    db: Annotated[Session, Depends(get_db)],
    limit: int = Query(default=50, ge=1, le=200),
) -> list[MessageResponse]:
    """Get messages for a conversation.

    Args:
        conversation_id: Conversation ID
        db: Database session
        limit: Maximum messages to return

    Returns:
        List of messages
    """
    conv = get_conversation(db, conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    messages = (
        db.query(Message)
        .filter(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.asc())
        .limit(limit)
        .all()
    )

    return [
        MessageResponse(
            id=msg.id,
            conversation_id=msg.conversation_id,
            role=msg.role.value,
            content=msg.content,
            created_at=msg.created_at.isoformat(),
        )
        for msg in messages
    ]


@router.delete("/conversations/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversation_endpoint(
    conversation_id: str,
    db: Annotated[Session, Depends(get_db)],
) -> None:
    """Delete a conversation and all its messages.

    Args:
        conversation_id: Conversation ID
        db: Database session
    """
    if not memory_delete_conversation(db, conversation_id):
        raise HTTPException(status_code=404, detail="Conversation not found")


@router.post("/conversations/{conversation_id}/clear", response_model=ConversationResponse)
async def clear_conversation_endpoint(
    conversation_id: str,
    db: Annotated[Session, Depends(get_db)],
) -> ConversationResponse:
    """Clear all messages from a conversation (keeps conversation).

    Args:
        conversation_id: Conversation ID
        db: Database session

    Returns:
        Updated conversation
    """
    conv = get_conversation(db, conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    clear_conversation_messages(db, conversation_id)
    db.refresh(conv)

    return ConversationResponse(
        id=conv.id,
        title=conv.title,
        is_active=conv.is_active,
        summary=conv.summary,
        created_at=conv.created_at.isoformat(),
        updated_at=conv.updated_at.isoformat(),
        message_count=0,
    )


# Multi-turn Q&A
@router.post("/qa/multi-turn", response_model=MultiTurnAnswerResponse)
async def multi_turn_query(
    req: MultiTurnQuestionRequest,
    db: Annotated[Session, Depends(get_db)],
    context: Annotated[RequestContext, Depends(require_request_context)],
) -> MultiTurnAnswerResponse:
    """Answer a question with conversation context.

    Args:
        req: Multi-turn question request
        db: Database session
        context: Request context with knowledge base scope

    Returns:
        Answer with conversation context
    """
    # Get or create conversation
    if req.conversation_id:
        conv = get_conversation(db, req.conversation_id)
        if not conv:
            raise HTTPException(status_code=404, detail="Conversation not found")
        conversation_id = req.conversation_id
    else:
        db_conv = create_conversation(db)
        conversation_id = db_conv.id

    # Add user message
    add_message_to_conversation(
        db=db,
        conversation_id=conversation_id,
        role=MessageRole.USER,
        content=req.question,
    )

    # Get answer with context
    result = answer_question_multi_turn(
        question=req.question,
        knowledge_base_id=context.knowledge_base.id,
        conversation_id=conversation_id if req.include_history else None,
        include_history=req.include_history,
    )

    # Store assistant message
    add_message_to_conversation(
        db=db,
        conversation_id=conversation_id,
        role=MessageRole.ASSISTANT,
        content=result["answer"],
    )

    # Enrich sources
    enriched_sources = []
    for source in result["sources"]:
        enriched_sources.append(
            SourceResponse(
                document_id=source["document_id"],
                chunk_content=source["chunk_content"],
                relevance_score=source["relevance_score"],
            )
        )

    return MultiTurnAnswerResponse(
        answer=result["answer"],
        conversation_id=conversation_id,
        sources=enriched_sources,
        processing_time_ms=result["processing_time_ms"],
    )


async def multi_turn_stream_event_generator(
    question: str,
    knowledge_base_id: str,
    conversation_id: str | None = None,
    include_history: bool = True,
) -> AsyncGenerator[str, None]:
    """Generate SSE events for streaming multi-turn answer.

    Args:
        question: User question
        knowledge_base_id: Knowledge base ID for retrieval filtering
        conversation_id: Conversation ID
        include_history: Include conversation history

    Yields:
        SSE formatted event strings
    """
    try:
        async for event in answer_question_multi_turn_stream(
            question=question,
            knowledge_base_id=knowledge_base_id,
            conversation_id=conversation_id,
            include_history=include_history,
        ):
            yield f"data: {json.dumps(event)}\n\n"
    except Exception as e:
        yield f"data: {json.dumps({'event': 'error', 'data': str(e)})}\n\n"


@router.post("/qa/multi-turn/stream")
async def stream_multi_turn_query(
    req: MultiTurnQuestionRequest,
    db: Annotated[Session, Depends(get_db)],
    context: Annotated[RequestContext, Depends(require_request_context)],
):
    """Stream answer with conversation context.

    Args:
        req: Multi-turn question request
        db: Database session

    Returns:
        StreamingResponse with SSE events
    """
    # Get or create conversation
    if req.conversation_id:
        conv = get_conversation(db, req.conversation_id)
        if not conv:
            raise HTTPException(status_code=404, detail="Conversation not found")
        conversation_id = req.conversation_id
    else:
        db_conv = create_conversation(db)
        conversation_id = db_conv.id

    # Add user message
    add_message_to_conversation(
        db=db,
        conversation_id=conversation_id,
        role=MessageRole.USER,
        content=req.question,
    )

    # Store conversation_id for the generator to access
    async def generator():
        async for event in answer_question_multi_turn_stream(
            question=req.question,
            knowledge_base_id=context.knowledge_base.id,
            conversation_id=conversation_id if req.include_history else None,
            include_history=req.include_history,
        ):
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
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
    from app.core.config import get_settings
    from app.db.vectorstore import get_vector_store
    from app.services.llm import check_ark_health, check_ollama_health

    settings = get_settings()

    # Check MySQL
    mysql_status = "connected"
    try:
        db.execute(text("SELECT 1"))
        db.commit()
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

    # Check Ark
    ark_status = "configured" if check_ark_health() else "not configured"

    overall_status = "ok"
    if mysql_status != "connected" or chroma_status != "connected":
        overall_status = "degraded"

    return HealthResponse(
        status=overall_status,
        mysql=mysql_status,
        chroma=chroma_status,
        ollama=ollama_status,
        ark=ark_status,
        llm_provider=settings.llm_provider.value,
    )
