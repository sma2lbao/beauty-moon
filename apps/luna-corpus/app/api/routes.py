"""API routes for luna-corpus."""

import json
import time
from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.api.auth import AuthenticatedRequestContext, require_permission
from app.auth.permissions import PermissionSlug
from app.core.config import get_settings
from app.db.database import SessionLocal, get_db
from app.db.models import (
    AuditResult,
    ContentStatus,
    Conversation,
    Document,
    FileUpload,
    Message,
    MessageRole,
    TaskStatus,
    TaskType,
)
from app.graph.rag_graph import (
    answer_question,
    answer_question_multi_turn,
    answer_question_multi_turn_stream,
    answer_question_stream,
)
from app.metadata.validation import load_field_definitions
from app.observability.metrics import INDEX_TASK_DURATION
from app.retrieval.filters import MetadataFilter
from app.security.audit import AuditAction, AuditService
from app.services.ingestion.exceptions import (
    DuplicateFileError,
    EmptyFileError,
    UnsupportedFileTypeError,
)
from app.services.ingestion.parsers import get_parser_registry
from app.services.ingestion.service import IngestionService
from app.services.ingestion.storage import get_storage_backend
from app.services.ingestion.tasks import TaskService
from app.services.memory import (
    add_message_to_conversation,
    clear_conversation_messages,
    create_conversation,
    get_conversation,
    get_message_count,
)
from app.services.memory import (
    delete_conversation as memory_delete_conversation,
)

router = APIRouter(prefix="/api/v1", tags=["qa"])


# Request/Response Models
class QuestionRequest(BaseModel):
    """Question request model."""

    question: str = Field(..., min_length=1, max_length=1000)
    top_k: int = Field(default=5, ge=1, le=20)
    filters: MetadataFilter | None = None


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


class ComponentHealth(BaseModel):
    """Health status of a single dependency."""

    status: str  # up | down | not_configured
    latency_ms: float | None = None
    provider: str | None = None


class HealthResponse(BaseModel):
    """Health check response."""

    status: str  # ok | degraded
    components: dict[str, ComponentHealth]


class ProcessResponse(BaseModel):
    """Document processing response."""

    status: str
    chunks_created: int


class TaskResponse(BaseModel):
    """Task response model."""

    id: str
    type: str
    status: str
    target_id: str
    error_message: str | None
    started_at: str | None
    completed_at: str | None
    created_at: str
    updated_at: str

    model_config = ConfigDict(from_attributes=True)


class TaskListResponse(BaseModel):
    """Task list response."""

    tasks: list[TaskResponse]
    total: int


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
    conversation_id: str | None = Field(
        default=None, description="Existing conversation ID"
    )
    include_history: bool = Field(
        default=True, description="Include conversation history"
    )


class MultiTurnAnswerResponse(BaseModel):
    """Multi-turn answer response."""

    answer: str
    conversation_id: str
    sources: list[SourceResponse]
    processing_time_ms: int


class FileUploadResponse(BaseModel):
    """File upload response model."""

    id: str
    knowledge_base_id: str
    original_name: str
    mime_type: str
    size_bytes: int
    content_hash: str
    status: str
    error_message: str | None
    parsed_at: str | None
    created_at: str
    updated_at: str

    model_config = ConfigDict(from_attributes=True)


class FileUploadListResponse(BaseModel):
    """File upload list response."""

    files: list[FileUploadResponse]
    total: int


class FileUploadCreateResponse(BaseModel):
    """File upload creation response with document and task info."""

    file: FileUploadResponse
    document_id: str | None
    task_id: str | None


def _run_index_task(task_id: str, document_id: str) -> None:
    """Background task: chunk, embed, and vectorize a document.

    Runs in its own DB session. Catches all exceptions and updates
    task status accordingly.
    """
    from app.services.document_processor import DocumentProcessor

    db = SessionLocal()
    start = time.perf_counter()
    try:
        task_service = TaskService()
        task_service.mark_running(db, task_id)

        processor = DocumentProcessor()
        processor.process_document(db, document_id)
        INDEX_TASK_DURATION.labels(result="success").observe(
            time.perf_counter() - start
        )

        task_service.mark_completed(db, task_id)
        AuditService().record(
            db,
            action=AuditAction.DOCUMENT_INDEX,
            resource_type="document",
            resource_id=document_id,
            result=AuditResult.SUCCESS,
            context=None,
        )
        db.commit()
    except Exception as e:
        task_service = TaskService()
        task_service.mark_failed(db, task_id, error_message=str(e))
        INDEX_TASK_DURATION.labels(result="failure").observe(
            time.perf_counter() - start
        )
        AuditService().record_failure(
            action=AuditAction.DOCUMENT_INDEX,
            resource_type="document",
            resource_id=document_id,
            context=None,
            detail=str(e),
        )
    finally:
        db.close()


# Question Answering
@router.post("/qa/query", response_model=AnswerResponse)
async def query(
    question_req: QuestionRequest,
    db: Annotated[Session, Depends(get_db)],
    context: Annotated[
        AuthenticatedRequestContext,
        Depends(require_permission(PermissionSlug.QA_QUERY)),
    ],
) -> AnswerResponse:
    """Answer a question using RAG.

    Args:
        question_req: Question request
        db: Database session
        context: Request context with knowledge base scope

    Returns:
        Answer with sources
    """
    filters_payload = None
    field_types_payload = None
    if question_req.filters and question_req.filters.conditions:
        filters_payload = question_req.filters.model_dump()
        field_types_payload = {
            f.key: f.field_type.value
            for f in load_field_definitions(db, context.knowledge_base.id)
        }

    result = answer_question(
        question_req.question,
        knowledge_base_id=context.knowledge_base.id,
        filters=filters_payload,
        field_types=field_types_payload,
    )

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

    AuditService().record(
        db,
        action=AuditAction.QA_QUERY,
        resource_type="knowledge_base",
        resource_id=context.knowledge_base.id,
        result=AuditResult.SUCCESS,
        context=context,
    )
    db.commit()

    return AnswerResponse(
        answer=result["answer"],
        sources=enriched_sources,
        processing_time_ms=result["processing_time_ms"],
    )


async def stream_event_generator(
    question: str, knowledge_base_id: str
) -> AsyncGenerator[str, None]:
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
    db: Annotated[Session, Depends(get_db)],
    context: Annotated[
        AuthenticatedRequestContext,
        Depends(require_permission(PermissionSlug.QA_QUERY)),
    ],
):
    """Stream answer to a question using RAG.

    Args:
        question_req: Question request
        db: Database session
        context: Request context with knowledge base scope

    Returns:
        StreamingResponse with SSE events
    """
    AuditService().record(
        db,
        action=AuditAction.QA_QUERY,
        resource_type="knowledge_base",
        resource_id=context.knowledge_base.id,
        result=AuditResult.SUCCESS,
        context=context,
    )
    db.commit()

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
@router.post(
    "/documents",
    response_model=DocumentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_document(
    doc: DocumentCreate,
    db: Annotated[Session, Depends(get_db)],
    context: Annotated[
        AuthenticatedRequestContext,
        Depends(require_permission(PermissionSlug.DOCUMENT_WRITE)),
    ],
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
    db.flush()
    AuditService().record(
        db,
        action=AuditAction.DOCUMENT_CREATE,
        resource_type="document",
        resource_id=db_doc.id,
        result=AuditResult.SUCCESS,
        context=context,
    )
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
    context: Annotated[
        AuthenticatedRequestContext,
        Depends(require_permission(PermissionSlug.DOCUMENT_READ)),
    ],
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
    context: Annotated[
        AuthenticatedRequestContext,
        Depends(require_permission(PermissionSlug.DOCUMENT_READ)),
    ],
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
    context: Annotated[
        AuthenticatedRequestContext,
        Depends(require_permission(PermissionSlug.DOCUMENT_DELETE)),
    ],
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
        AuditService().record_failure(
            action=AuditAction.DOCUMENT_DELETE,
            resource_type="document",
            resource_id=document_id,
            context=context,
            detail="not found",
        )
        raise HTTPException(status_code=404, detail="Document not found")

    db.delete(doc)
    AuditService().record(
        db,
        action=AuditAction.DOCUMENT_DELETE,
        resource_type="document",
        resource_id=document_id,
        result=AuditResult.SUCCESS,
        context=context,
    )
    db.commit()


@router.post("/documents/{document_id}/process")
async def process_document(
    document_id: str,
    background_tasks: BackgroundTasks,
    db: Annotated[Session, Depends(get_db)],
    context: Annotated[
        AuthenticatedRequestContext,
        Depends(require_permission(PermissionSlug.DOCUMENT_WRITE)),
    ],
) -> dict[str, str]:
    """Queue a document for processing (chunk + vectorize).

    Args:
        document_id: Document ID
        background_tasks: FastAPI background tasks
        db: Database session
        context: Request context with knowledge base scope

    Returns:
        Task ID and status
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

    task_service = TaskService()
    task = task_service.create_task(
        db, TaskType.DOCUMENT_INDEX, doc.id, context.knowledge_base.id
    )
    background_tasks.add_task(_run_index_task, task.id, doc.id)

    return {"task_id": task.id, "status": task.status.value}


# Conversation Management
@router.post(
    "/conversations",
    response_model=ConversationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_conversation_endpoint(
    conv: ConversationCreate,
    db: Annotated[Session, Depends(get_db)],
    context: Annotated[
        AuthenticatedRequestContext,
        Depends(require_permission(PermissionSlug.CONVERSATION_WRITE)),
    ],
) -> ConversationResponse:
    """Create a new conversation.

    Args:
        conv: Conversation data
        db: Database session
        context: Request context with knowledge base scope

    Returns:
        Created conversation
    """
    db_conv = create_conversation(db, context.knowledge_base.id, conv.title)

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
    context: Annotated[
        AuthenticatedRequestContext,
        Depends(require_permission(PermissionSlug.CONVERSATION_READ)),
    ],
    active_only: bool = Query(default=True),
    limit: int = Query(default=50, ge=1, le=100),
) -> ConversationListResponse:
    """List all conversations.

    Args:
        db: Database session
        context: Request context with knowledge base scope
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

    # Main query with LEFT JOIN to message counts, scoped to knowledge base
    query = (
        db.query(Conversation, message_count_subq.c.message_count)
        .outerjoin(
            message_count_subq,
            Conversation.id == message_count_subq.c.conversation_id,
        )
        .filter(Conversation.knowledge_base_id == context.knowledge_base.id)
    )

    if active_only:
        query = query.filter(Conversation.is_active)

    results = query.order_by(Conversation.updated_at.desc()).limit(limit).all()

    conversations_response = []
    for conv, message_count in results:
        conversations_response.append(
            ConversationResponse(
                id=conv.id,
                title=conv.title,
                is_active=conv.is_active,
                summary=conv.summary,
                created_at=conv.created_at.isoformat(),
                updated_at=conv.updated_at.isoformat(),
                message_count=message_count or 0,
            )
        )

    return ConversationListResponse(
        conversations=conversations_response,
        total=len(conversations_response),
    )


@router.get("/conversations/{conversation_id}", response_model=ConversationResponse)
async def get_conversation_endpoint(
    conversation_id: str,
    db: Annotated[Session, Depends(get_db)],
    context: Annotated[
        AuthenticatedRequestContext,
        Depends(require_permission(PermissionSlug.CONVERSATION_READ)),
    ],
) -> ConversationResponse:
    """Get a conversation by ID.

    Args:
        conversation_id: Conversation ID
        db: Database session
        context: Request context with knowledge base scope

    Returns:
        Conversation
    """
    conv = get_conversation(db, conversation_id, context.knowledge_base.id)
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


@router.get(
    "/conversations/{conversation_id}/messages",
    response_model=list[MessageResponse],
)
async def get_conversation_messages_endpoint(
    conversation_id: str,
    db: Annotated[Session, Depends(get_db)],
    context: Annotated[
        AuthenticatedRequestContext,
        Depends(require_permission(PermissionSlug.CONVERSATION_READ)),
    ],
    limit: int = Query(default=50, ge=1, le=200),
) -> list[MessageResponse]:
    """Get messages for a conversation.

    Args:
        conversation_id: Conversation ID
        db: Database session
        context: Request context with knowledge base scope
        limit: Maximum messages to return

    Returns:
        List of messages
    """
    conv = get_conversation(db, conversation_id, context.knowledge_base.id)
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


@router.delete(
    "/conversations/{conversation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_conversation_endpoint(
    conversation_id: str,
    db: Annotated[Session, Depends(get_db)],
    context: Annotated[
        AuthenticatedRequestContext,
        Depends(require_permission(PermissionSlug.CONVERSATION_DELETE)),
    ],
) -> None:
    """Delete a conversation and all its messages.

    Args:
        conversation_id: Conversation ID
        db: Database session
        context: Request context with knowledge base scope
    """
    conv = get_conversation(db, conversation_id, context.knowledge_base.id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if not memory_delete_conversation(db, conversation_id):
        raise HTTPException(status_code=404, detail="Conversation not found")


@router.post(
    "/conversations/{conversation_id}/clear",
    response_model=ConversationResponse,
)
async def clear_conversation_endpoint(
    conversation_id: str,
    db: Annotated[Session, Depends(get_db)],
    context: Annotated[
        AuthenticatedRequestContext,
        Depends(require_permission(PermissionSlug.CONVERSATION_WRITE)),
    ],
) -> ConversationResponse:
    """Clear all messages from a conversation (keeps conversation).

    Args:
        conversation_id: Conversation ID
        db: Database session
        context: Request context with knowledge base scope

    Returns:
        Updated conversation
    """
    conv = get_conversation(db, conversation_id, context.knowledge_base.id)
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
    context: Annotated[
        AuthenticatedRequestContext,
        Depends(
            require_permission(
                PermissionSlug.QA_QUERY, PermissionSlug.CONVERSATION_WRITE
            )
        ),
    ],
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
        conv = get_conversation(db, req.conversation_id, context.knowledge_base.id)
        if not conv:
            raise HTTPException(status_code=404, detail="Conversation not found")
        conversation_id = req.conversation_id
    else:
        db_conv = create_conversation(db, context.knowledge_base.id)
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

    AuditService().record(
        db,
        action=AuditAction.QA_QUERY,
        resource_type="knowledge_base",
        resource_id=context.knowledge_base.id,
        result=AuditResult.SUCCESS,
        context=context,
    )
    db.commit()

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
    context: Annotated[
        AuthenticatedRequestContext,
        Depends(
            require_permission(
                PermissionSlug.QA_QUERY, PermissionSlug.CONVERSATION_WRITE
            )
        ),
    ],
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
        conv = get_conversation(db, req.conversation_id, context.knowledge_base.id)
        if not conv:
            raise HTTPException(status_code=404, detail="Conversation not found")
        conversation_id = req.conversation_id
    else:
        db_conv = create_conversation(db, context.knowledge_base.id)
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

    AuditService().record(
        db,
        action=AuditAction.QA_QUERY,
        resource_type="knowledge_base",
        resource_id=context.knowledge_base.id,
        result=AuditResult.SUCCESS,
        context=context,
    )
    db.commit()

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# File Upload Management
@router.post(
    "/files/upload",
    response_model=FileUploadCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_file(
    file: UploadFile,
    background_tasks: BackgroundTasks,
    db: Annotated[Session, Depends(get_db)],
    context: Annotated[
        AuthenticatedRequestContext,
        Depends(require_permission(PermissionSlug.DOCUMENT_WRITE)),
    ],
) -> FileUploadCreateResponse:
    """Upload a file, parse it, create a document, and queue for indexing.

    Args:
        file: Uploaded file
        background_tasks: FastAPI background tasks
        db: Database session
        context: Request context with knowledge base scope

    Returns:
        Created file upload, document info, and task info
    """
    storage = get_storage_backend()
    registry = get_parser_registry()

    service = IngestionService(
        storage=storage,
        parser_registry=registry,
        max_upload_size=get_settings().max_upload_size,
        duplicate_policy=get_settings().upload_duplicate_policy,
    )

    try:
        upload, document = await service.ingest_file(
            db, file, context.knowledge_base.id
        )
    except EmptyFileError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
        ) from e
    except UnsupportedFileTypeError as e:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=str(e),
        ) from e
    except DuplicateFileError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e),
        ) from e
    except Exception as e:
        # Re-raise HTTPExceptions as-is
        if isinstance(e, HTTPException):
            raise
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        ) from e

    document_id = None
    task_id = None

    if document is not None:
        document_id = document.id
        task_service = TaskService()
        task = task_service.create_task(
            db, TaskType.DOCUMENT_INDEX, document.id, context.knowledge_base.id
        )
        task_id = task.id
        background_tasks.add_task(_run_index_task, task.id, document.id)

    return FileUploadCreateResponse(
        file=FileUploadResponse(
            id=upload.id,
            knowledge_base_id=upload.knowledge_base_id,
            original_name=upload.original_name,
            mime_type=upload.mime_type,
            size_bytes=upload.size_bytes,
            content_hash=upload.content_hash,
            status=upload.status.value,
            error_message=upload.error_message,
            parsed_at=upload.parsed_at.isoformat() if upload.parsed_at else None,
            created_at=upload.created_at.isoformat(),
            updated_at=upload.updated_at.isoformat(),
        ),
        document_id=document_id,
        task_id=task_id,
    )


@router.get("/files", response_model=FileUploadListResponse)
async def list_files(
    db: Annotated[Session, Depends(get_db)],
    context: Annotated[
        AuthenticatedRequestContext,
        Depends(require_permission(PermissionSlug.DOCUMENT_READ)),
    ],
) -> FileUploadListResponse:
    """List uploaded files for the knowledge base.

    Args:
        db: Database session
        context: Request context with knowledge base scope

    Returns:
        List of file uploads
    """
    uploads = (
        db.query(FileUpload)
        .filter(FileUpload.knowledge_base_id == context.knowledge_base.id)
        .order_by(FileUpload.created_at.desc())
        .all()
    )

    return FileUploadListResponse(
        files=[
            FileUploadResponse(
                id=u.id,
                knowledge_base_id=u.knowledge_base_id,
                original_name=u.original_name,
                mime_type=u.mime_type,
                size_bytes=u.size_bytes,
                content_hash=u.content_hash,
                status=u.status.value,
                error_message=u.error_message,
                parsed_at=u.parsed_at.isoformat() if u.parsed_at else None,
                created_at=u.created_at.isoformat(),
                updated_at=u.updated_at.isoformat(),
            )
            for u in uploads
        ],
        total=len(uploads),
    )


@router.get("/files/{file_id}", response_model=FileUploadResponse)
async def get_file(
    file_id: str,
    db: Annotated[Session, Depends(get_db)],
    context: Annotated[
        AuthenticatedRequestContext,
        Depends(require_permission(PermissionSlug.DOCUMENT_READ)),
    ],
) -> FileUploadResponse:
    """Get a file upload record by ID.

    Args:
        file_id: File upload ID
        db: Database session
        context: Request context with knowledge base scope

    Returns:
        File upload record
    """
    upload = (
        db.query(FileUpload)
        .filter(
            FileUpload.id == file_id,
            FileUpload.knowledge_base_id == context.knowledge_base.id,
        )
        .first()
    )
    if not upload:
        raise HTTPException(status_code=404, detail="File not found")

    return FileUploadResponse(
        id=upload.id,
        knowledge_base_id=upload.knowledge_base_id,
        original_name=upload.original_name,
        mime_type=upload.mime_type,
        size_bytes=upload.size_bytes,
        content_hash=upload.content_hash,
        status=upload.status.value,
        error_message=upload.error_message,
        parsed_at=upload.parsed_at.isoformat() if upload.parsed_at else None,
        created_at=upload.created_at.isoformat(),
        updated_at=upload.updated_at.isoformat(),
    )


@router.delete("/files/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_file(
    file_id: str,
    db: Annotated[Session, Depends(get_db)],
    context: Annotated[
        AuthenticatedRequestContext,
        Depends(require_permission(PermissionSlug.DOCUMENT_DELETE)),
    ],
) -> None:
    """Delete a file and its associated document.

    Args:
        file_id: File upload ID
        db: Database session
        context: Request context with knowledge base scope
    """
    storage = get_storage_backend()
    registry = get_parser_registry()

    service = IngestionService(
        storage=storage,
        parser_registry=registry,
    )

    await service.delete_file(db, file_id, context.knowledge_base.id)


# Task Management
@router.get("/tasks", response_model=TaskListResponse)
async def list_tasks(
    db: Annotated[Session, Depends(get_db)],
    context: Annotated[
        AuthenticatedRequestContext,
        Depends(require_permission(PermissionSlug.DOCUMENT_READ)),
    ],
    status_filter: TaskStatus | None = None,
    limit: int = Query(default=50, ge=1, le=100),
) -> TaskListResponse:
    """List ingestion tasks for the knowledge base.

    Args:
        db: Database session
        context: Request context with knowledge base scope
        status_filter: Optional status filter
        limit: Maximum tasks to return

    Returns:
        List of tasks
    """
    task_service = TaskService()
    tasks = task_service.list_tasks(
        db, context.knowledge_base.id, status=status_filter, limit=limit
    )

    return TaskListResponse(
        tasks=[
            TaskResponse(
                id=t.id,
                type=t.type.value,
                status=t.status.value,
                target_id=t.target_id,
                error_message=t.error_message,
                started_at=t.started_at.isoformat() if t.started_at else None,
                completed_at=t.completed_at.isoformat() if t.completed_at else None,
                created_at=t.created_at.isoformat(),
                updated_at=t.updated_at.isoformat(),
            )
            for t in tasks
        ],
        total=len(tasks),
    )


@router.get("/tasks/{task_id}", response_model=TaskResponse)
async def get_task(
    task_id: str,
    db: Annotated[Session, Depends(get_db)],
    context: Annotated[
        AuthenticatedRequestContext,
        Depends(require_permission(PermissionSlug.DOCUMENT_READ)),
    ],
) -> TaskResponse:
    """Get a task by ID.

    Args:
        task_id: Task ID
        db: Database session
        context: Request context with knowledge base scope

    Returns:
        Task
    """
    task_service = TaskService()
    task = task_service.get_task(db, task_id)

    if not task or task.knowledge_base_id != context.knowledge_base.id:
        raise HTTPException(status_code=404, detail="Task not found")

    return TaskResponse(
        id=task.id,
        type=task.type.value,
        status=task.status.value,
        target_id=task.target_id,
        error_message=task.error_message,
        started_at=task.started_at.isoformat() if task.started_at else None,
        completed_at=task.completed_at.isoformat() if task.completed_at else None,
        created_at=task.created_at.isoformat(),
        updated_at=task.updated_at.isoformat(),
    )


# Health Check
@router.get("/health", response_model=HealthResponse)
async def health_check(db: Annotated[Session, Depends(get_db)]) -> HealthResponse:
    """Report per-component health (database, vectorstore, llm_provider)."""

    from app.db.vectorstore import get_vector_store
    from app.services.llm import (
        check_ark_health,
        check_doubao_health,
        check_ollama_health,
    )

    settings = get_settings()
    components: dict[str, ComponentHealth] = {}

    # Database
    start = time.perf_counter()
    try:
        db.execute(text("SELECT 1"))
        db.commit()
        components["database"] = ComponentHealth(
            status="up", latency_ms=round((time.perf_counter() - start) * 1000, 2)
        )
    except Exception:
        components["database"] = ComponentHealth(status="down")

    # Vector store
    start = time.perf_counter()
    try:
        get_vector_store()
        components["vectorstore"] = ComponentHealth(
            status="up", latency_ms=round((time.perf_counter() - start) * 1000, 2)
        )
    except Exception:
        components["vectorstore"] = ComponentHealth(status="down")

    # LLM provider — only the configured provider is probed.
    provider = settings.llm_provider.value
    check = {
        "ollama": check_ollama_health,
        "ark": check_ark_health,
        "doubao": check_doubao_health,
    }.get(provider)
    try:
        healthy = bool(check()) if check else False
        provider_status = "up" if healthy else "not_configured"
    except Exception:
        provider_status = "down"
    components["llm_provider"] = ComponentHealth(
        status=provider_status, provider=provider
    )

    overall = "ok"
    if (
        components["database"].status == "down"
        or components["vectorstore"].status == "down"
    ):
        overall = "degraded"

    return HealthResponse(status=overall, components=components)
