"""LangGraph RAG flow for question answering."""
import time
import uuid
from typing import Any, AsyncGenerator

from langgraph.graph import END, StateGraph

from app.core.config import RetrievalMode, get_settings
from app.db.database import SessionLocal, get_db
from app.db.models import Chunk, Document
from app.graph.state import RAGState
from app.metadata.schema import FieldType
from app.observability.metrics import (
    LLM_GENERATION_DURATION,
    time_stage,
)
from app.retrieval.filters import MetadataFilter
from app.retrieval.hybrid import hybrid_search
from app.services.llm import (
    embed_text,
    generate_response,
    generate_response_with_usage,
    generate_streaming_response,
)
from app.services.memory import (
    format_conversation_history,
    get_conversation_messages,
    get_memory_context,
)
from app.services.prompt_builder import build_rag_prompt, render_prompt
from app.prompts.experiment import select_version
from app.prompts.defaults import RAG_QA_PROMPT_KEY

settings = get_settings()


def validate_retrieved_docs_for_knowledge_base(
    retrieved_docs: list[dict[str, Any]],
    knowledge_base_id: str,
) -> list[dict[str, Any]]:
    """Keep only retrieved docs whose SQL document belongs to the knowledge base.

    同时从 Chunk 行补齐定位字段（chunk_index/char_start/char_end/heading_path），
    供 sources 透出。存量 chunk 缺失定位时保持 None。
    """
    chunk_ids = {
        doc.get("chunk_id") for doc in retrieved_docs if doc.get("chunk_id")
    }
    if not chunk_ids:
        return []

    db = next(get_db())
    try:
        rows = (
            db.query(
                Chunk.id,
                Chunk.chunk_index,
                Chunk.char_start,
                Chunk.char_end,
                Chunk.heading_path,
            )
            .join(Document, Chunk.document_id == Document.id)
            .filter(
                Chunk.id.in_(chunk_ids),
                Document.knowledge_base_id == knowledge_base_id,
            )
            .all()
        )
    finally:
        db.close()

    locator_by_chunk = {
        row[0]: {
            "chunk_index": row[1],
            "char_start": row[2],
            "char_end": row[3],
            "heading_path": row[4],
        }
        for row in rows
    }

    validated = []
    for doc in retrieved_docs:
        loc = locator_by_chunk.get(doc.get("chunk_id"))
        if loc is None:
            continue  # 不属于该 KB，过滤掉
        validated.append({**doc, **loc})
    return validated


def format_sources(retrieved_docs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Format validated retrieved docs as API sources."""
    return [
        {
            "document_id": doc["document_id"],
            "chunk_content": doc["content"][:200] + "..."
            if len(doc["content"]) > 200
            else doc["content"],
            "relevance_score": doc["score"],
            "chunk_index": doc.get("chunk_index"),
            "char_start": doc.get("char_start"),
            "char_end": doc.get("char_end"),
            "heading_path": doc.get("heading_path"),
        }
        for doc in retrieved_docs
    ]


def retrieve_memory_node(state: RAGState) -> dict[str, Any]:
    """Retrieve conversation history from memory.

    Args:
        state: Current RAG state

    Returns:
        Updated state with conversation history
    """
    conversation_id = state.get("conversation_id")

    if not conversation_id:
        return {
            "conversation_history": [],
            "needs_summarization": False,
        }

    db = SessionLocal()
    try:
        messages = get_conversation_messages(db, conversation_id)
        formatted_history = format_conversation_history(messages)
        needs_summarization = len(messages) >= settings.conversation_summarize_threshold

        return {
            "conversation_history": [
                {
                    "id": m.id,
                    "role": m.role.value,
                    "content": m.content,
                    "created_at": m.created_at.isoformat(),
                }
                for m in messages
            ],
            "needs_summarization": needs_summarization,
        }
    finally:
        db.close()


def retrieve_node(state: RAGState) -> dict[str, Any]:
    """Retrieve relevant documents from vector store.

    Args:
        state: Current RAG state

    Returns:
        Updated state with retrieved documents
    """
    question = state["question"]
    knowledge_base_id = state.get("knowledge_base_id")

    # Generate query embedding
    query_embedding = embed_text(question)

    filters_raw = state.get("filters")
    field_types_raw = state.get("field_types")
    filters = MetadataFilter(**filters_raw) if filters_raw else None
    field_types = (
        {k: FieldType(v) for k, v in field_types_raw.items()}
        if field_types_raw
        else None
    )

    # Retrieve documents (vector or hybrid, per settings.retrieval_mode)
    results = hybrid_search(
        question,
        query_embedding,
        top_k=settings.retrieval_top_k,
        knowledge_base_id=knowledge_base_id,
        filters=filters,
        field_types=field_types,
    )

    # Format retrieved docs
    retrieved_docs = []
    for result in results:
        retrieved_docs.append({
            "chunk_id": result["chunk_id"],
            "document_id": result["document_id"],
            "content": result["content"],
            "score": result.get("score", 0.0),
        })

    retrieved_docs = validate_retrieved_docs_for_knowledge_base(
        retrieved_docs,
        knowledge_base_id,
    )

    return {"retrieved_docs": retrieved_docs}


def generate_node(state: RAGState) -> dict[str, Any]:
    """Generate answer from retrieved documents and conversation context.

    Args:
        state: Current RAG state

    Returns:
        Updated state with generated answer
    """
    question = state["question"]
    retrieved_docs = state["retrieved_docs"]
    conversation_id = state.get("conversation_id")

    conversation_history = ""
    conversation_summary = None

    if conversation_id and state.get("conversation_history"):
        for msg in state["conversation_history"]:
            role = "User" if msg["role"] == "user" else "Assistant"
            conversation_history += f"{role}: {msg['content']}\n\n"

        if state.get("needs_summarization"):
            db = SessionLocal()
            try:
                context_str, _ = get_memory_context(db, conversation_id)
                conversation_summary = context_str
            finally:
                db.close()

    if not retrieved_docs and not conversation_history:
        return {
            "answer": "I couldn't find any relevant information to answer your question.",
            "sources": [],
            "prompt_version_id": None,
        }

    # Build context from retrieved docs
    context_parts = []
    for i, doc in enumerate(retrieved_docs):
        context_parts.append(f"[Source {i+1}]\n{doc['content']}")

    context = "\n\n".join(context_parts)

    # Select prompt version (A/B), then render. Fail-safe to file default.
    knowledge_base_id = state.get("knowledge_base_id")
    # Split seed: reuse conversation_id for stable per-conversation bucketing;
    # for single-turn requests fall back to a fresh per-request seed so traffic
    # is actually split across variants instead of pinning a whole KB to one.
    seed = conversation_id or uuid.uuid4().hex
    db = SessionLocal()
    try:
        resolved = select_version(
            db, knowledge_base_id, RAG_QA_PROMPT_KEY, "zh", seed=seed
        )
    finally:
        db.close()
    full_prompt = render_prompt(
        resolved.template_text,
        question=question,
        context=context,
        conversation_history=conversation_history,
        conversation_summary=conversation_summary,
    )
    prompt_version_id = resolved.version_id

    # Generate response
    with time_stage(LLM_GENERATION_DURATION, provider=settings.llm_provider.value):
        answer, usage = generate_response_with_usage(prompt=full_prompt, context=None)

    # Format sources
    sources = format_sources(retrieved_docs)

    return {
        "answer": answer,
        "sources": sources,
        "prompt_version_id": prompt_version_id,
        "usage": usage,
    }


def create_rag_graph() -> StateGraph:
    """Create the RAG question-answering graph.

    Returns:
        Compiled LangGraph for RAG
    """
    workflow = StateGraph(RAGState)

    # Add nodes
    workflow.add_node("retrieve_memory", retrieve_memory_node)
    workflow.add_node("retrieve", retrieve_node)
    workflow.add_node("generate", generate_node)

    # Set entry point
    workflow.set_entry_point("retrieve_memory")

    # Add edges
    workflow.add_edge("retrieve_memory", "retrieve")
    workflow.add_edge("retrieve", "generate")
    workflow.add_edge("generate", END)

    return workflow.compile()


# Singleton graph instance
_rag_graph = None


def get_rag_graph() -> StateGraph:
    """Get cached RAG graph instance."""
    global _rag_graph
    if _rag_graph is None:
        _rag_graph = create_rag_graph()
    return _rag_graph


def answer_question(
    question: str,
    knowledge_base_id: str,
    filters: dict | None = None,
    field_types: dict | None = None,
) -> dict[str, Any]:
    """Answer a question using RAG.

    Args:
        question: User question
        knowledge_base_id: Knowledge base ID for retrieval filtering
        filters: Optional MetadataFilter serialized as dict
        field_types: Optional mapping of field key to FieldType value

    Returns:
        Answer with sources and metadata
    """
    start_time = time.time()

    graph = get_rag_graph()
    result = graph.invoke({
        "question": question,
        "knowledge_base_id": knowledge_base_id,
        "conversation_id": None,
        "conversation_history": [],
        "retrieved_docs": [],
        "needs_summarization": False,
        "filters": filters,
        "field_types": field_types,
    })

    processing_time_ms = int((time.time() - start_time) * 1000)

    return {
        "answer": result["answer"],
        "sources": result["sources"],
        "processing_time_ms": processing_time_ms,
        "retrieval_mode": settings.retrieval_mode.value,
        "prompt_version_id": result.get("prompt_version_id"),
        "usage": result.get("usage"),
    }


async def answer_question_stream(
    question: str,
    knowledge_base_id: str,
    usage_holder: dict | None = None,
) -> AsyncGenerator[dict[str, Any], None]:
    """Stream answer to a question using RAG.

    Args:
        question: User question
        knowledge_base_id: Knowledge base ID for retrieval filtering

    Yields:
        Events: retrieval_status, token, done
    """
    start_time = time.time()

    # Generate query embedding (non-streaming)
    yield {
        "event": "retrieval_status",
        "data": "正在生成查询向量...",
    }

    query_embedding = embed_text(question)

    # Retrieve documents (vector or hybrid, per settings.retrieval_mode)
    retrieval_status = (
        "正在进行混合检索（向量 + 关键词）..."
        if settings.retrieval_mode == RetrievalMode.HYBRID
        else "正在检索相关文档..."
    )
    yield {
        "event": "retrieval_status",
        "data": retrieval_status,
    }

    results = hybrid_search(
        question,
        query_embedding,
        top_k=settings.retrieval_top_k,
        knowledge_base_id=knowledge_base_id,
    )

    retrieved_docs = [
        {
            "chunk_id": result["chunk_id"],
            "document_id": result["document_id"],
            "content": result["content"],
            "score": result.get("score", 0.0),
        }
        for result in results
    ]

    retrieved_docs = validate_retrieved_docs_for_knowledge_base(
        retrieved_docs,
        knowledge_base_id,
    )

    yield {
        "event": "retrieval_status",
        "data": f"检索到 {len(retrieved_docs)} 个相关文档",
    }

    if not retrieved_docs:
        yield {"event": "token", "data": "抱歉，我找不到相关的文档来回答您的问题。"}
        yield {
            "event": "done",
            "data": {"answer": "", "sources": [], "processing_time_ms": int((time.time() - start_time) * 1000)},
        }
        return

    # Build context from retrieved docs
    context_parts = []
    for i, doc in enumerate(retrieved_docs):
        context_parts.append(f"[Source {i+1}]\n{doc['content']}")

    context = "\n\n".join(context_parts)

    # Stream token generation
    yield {
        "event": "retrieval_status",
        "data": "正在生成回答...",
    }

    full_answer = ""
    async for token in generate_streaming_response(prompt=question, context=context, usage_holder=usage_holder):
        full_answer += token
        yield {"event": "token", "data": token}

    # Format sources
    sources = format_sources(retrieved_docs)

    processing_time_ms = int((time.time() - start_time) * 1000)

    yield {
        "event": "done",
        "data": {
            "answer": full_answer,
            "sources": sources,
            "processing_time_ms": processing_time_ms,
        },
    }


def answer_question_multi_turn(
    question: str,
    knowledge_base_id: str,
    conversation_id: str | None = None,
    include_history: bool = True,
) -> dict[str, Any]:
    """Answer a question with conversation context.

    Args:
        question: User question
        knowledge_base_id: Knowledge base ID for retrieval filtering
        conversation_id: Conversation ID for context
        include_history: Whether to include conversation history

    Returns:
        Answer with sources and metadata
    """
    start_time = time.time()

    graph = get_rag_graph()
    result = graph.invoke({
        "question": question,
        "knowledge_base_id": knowledge_base_id,
        "conversation_id": conversation_id if include_history else None,
        "conversation_history": [],
        "retrieved_docs": [],
        "needs_summarization": False,
    })

    processing_time_ms = int((time.time() - start_time) * 1000)

    return {
        "answer": result["answer"],
        "sources": result["sources"],
        "processing_time_ms": processing_time_ms,
        "conversation_id": conversation_id,
        "needs_summarization": result.get("needs_summarization", False),
        "retrieval_mode": settings.retrieval_mode.value,
        "prompt_version_id": result.get("prompt_version_id"),
    }


async def answer_question_multi_turn_stream(
    question: str,
    knowledge_base_id: str,
    conversation_id: str | None = None,
    include_history: bool = True,
) -> AsyncGenerator[dict[str, Any], None]:
    """Stream answer with conversation context.

    Args:
        question: User question
        knowledge_base_id: Knowledge base ID for retrieval filtering
        conversation_id: Conversation ID for context
        include_history: Whether to include conversation history

    Yields:
        Events: retrieval_status, token, done
    """
    start_time = time.time()

    conversation_history = ""
    conversation_summary = None

    if include_history and conversation_id:
        db = SessionLocal()
        try:
            messages = get_conversation_messages(db, conversation_id)
            conversation_history = format_conversation_history(messages)

            context_str, needs_sum = get_memory_context(db, conversation_id)
            if needs_sum:
                conversation_summary = context_str
        finally:
            db.close()

    # Generate query embedding (non-streaming)
    yield {
        "event": "retrieval_status",
        "data": "正在生成查询向量...",
    }

    query_embedding = embed_text(question)

    # Retrieve documents (vector or hybrid, per settings.retrieval_mode)
    retrieval_status = (
        "正在进行混合检索（向量 + 关键词）..."
        if settings.retrieval_mode == RetrievalMode.HYBRID
        else "正在检索相关文档..."
    )
    yield {
        "event": "retrieval_status",
        "data": retrieval_status,
    }

    results = hybrid_search(
        question,
        query_embedding,
        top_k=settings.retrieval_top_k,
        knowledge_base_id=knowledge_base_id,
    )

    retrieved_docs = [
        {
            "chunk_id": result["chunk_id"],
            "document_id": result["document_id"],
            "content": result["content"],
            "score": result.get("score", 0.0),
        }
        for result in results
    ]

    retrieved_docs = validate_retrieved_docs_for_knowledge_base(
        retrieved_docs,
        knowledge_base_id,
    )

    yield {
        "event": "retrieval_status",
        "data": f"检索到 {len(retrieved_docs)} 个相关文档",
    }

    if not retrieved_docs and not conversation_history:
        yield {
            "event": "token",
            "data": "抱歉，我找不到相关的文档来回答您的问题。",
        }
        yield {
            "event": "done",
            "data": {
                "answer": "",
                "sources": [],
                "processing_time_ms": int((time.time() - start_time) * 1000),
                "conversation_id": conversation_id,
            },
        }
        return

    # Build context from retrieved docs
    context_parts = []
    for i, doc in enumerate(retrieved_docs):
        context_parts.append(f"[Source {i+1}]\n{doc['content']}")

    context = "\n\n".join(context_parts)

    # Build complete prompt with conversation context
    full_prompt = build_rag_prompt(
        question=question,
        context=context,
        conversation_history=conversation_history,
        conversation_summary=conversation_summary,
    )

    # Stream token generation
    yield {
        "event": "retrieval_status",
        "data": "正在生成回答...",
    }

    full_answer = ""
    async for token in generate_streaming_response(prompt=full_prompt, context=None):
        full_answer += token
        yield {"event": "token", "data": token}

    # Format sources
    sources = format_sources(retrieved_docs)

    processing_time_ms = int((time.time() - start_time) * 1000)

    yield {
        "event": "done",
        "data": {
            "answer": full_answer,
            "sources": sources,
            "processing_time_ms": processing_time_ms,
            "conversation_id": conversation_id,
        },
    }
