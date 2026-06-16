"""LangGraph RAG flow for question answering."""
import time
from typing import Any, AsyncGenerator

from langgraph.graph import END, StateGraph

from app.core.config import get_settings
from app.db.vectorstore import search_vectorstore
from app.graph.state import RAGState
from app.services.llm import embed_text, generate_response, generate_streaming_response

settings = get_settings()


def retrieve_node(state: RAGState) -> dict[str, Any]:
    """Retrieve relevant documents from vector store.

    Args:
        state: Current RAG state

    Returns:
        Updated state with retrieved documents
    """
    question = state["question"]

    # Generate query embedding
    query_embedding = embed_text(question)

    # Search vector store
    results = search_vectorstore(
        query_embedding=query_embedding,
        top_k=settings.retrieval_top_k,
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

    return {"retrieved_docs": retrieved_docs}


def generate_node(state: RAGState) -> dict[str, Any]:
    """Generate answer from retrieved documents.

    Args:
        state: Current RAG state

    Returns:
        Updated state with generated answer
    """
    question = state["question"]
    retrieved_docs = state["retrieved_docs"]

    if not retrieved_docs:
        return {
            "answer": "I couldn't find any relevant information to answer your question.",
            "sources": [],
        }

    # Build context from retrieved docs
    context_parts = []
    for i, doc in enumerate(retrieved_docs):
        context_parts.append(f"[Source {i+1}]\n{doc['content']}")

    context = "\n\n".join(context_parts)

    # Generate response
    answer = generate_response(prompt=question, context=context)

    # Format sources
    sources = [
        {
            "document_id": doc["document_id"],
            "chunk_content": doc["content"][:200] + "..."
            if len(doc["content"]) > 200
            else doc["content"],
            "relevance_score": doc["score"],
        }
        for doc in retrieved_docs
    ]

    return {"answer": answer, "sources": sources}


def create_rag_graph() -> StateGraph:
    """Create the RAG question-answering graph.

    Returns:
        Compiled LangGraph for RAG
    """
    workflow = StateGraph(RAGState)

    # Add nodes
    workflow.add_node("retrieve", retrieve_node)
    workflow.add_node("generate", generate_node)

    # Set entry point
    workflow.set_entry_point("retrieve")

    # Add edges
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


def answer_question(question: str) -> dict[str, Any]:
    """Answer a question using RAG.

    Args:
        question: User question

    Returns:
        Answer with sources and metadata
    """
    start_time = time.time()

    graph = get_rag_graph()
    result = graph.invoke({"question": question, "retrieved_docs": []})

    processing_time_ms = int((time.time() - start_time) * 1000)

    return {
        "answer": result["answer"],
        "sources": result["sources"],
        "processing_time_ms": processing_time_ms,
    }


async def answer_question_stream(question: str) -> AsyncGenerator[dict[str, Any], None]:
    """Stream answer to a question using RAG.

    Args:
        question: User question

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

    # Search vector store
    yield {
        "event": "retrieval_status",
        "data": "正在检索相似文档...",
    }

    results = search_vectorstore(
        query_embedding=query_embedding,
        top_k=settings.retrieval_top_k,
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
    async for token in generate_streaming_response(prompt=question, context=context):
        full_answer += token
        yield {"event": "token", "data": token}

    # Format sources
    sources = [
        {
            "document_id": doc["document_id"],
            "chunk_content": doc["content"][:200] + "..." if len(doc["content"]) > 200 else doc["content"],
            "relevance_score": doc["score"],
        }
        for doc in retrieved_docs
    ]

    processing_time_ms = int((time.time() - start_time) * 1000)

    yield {
        "event": "done",
        "data": {
            "answer": full_answer,
            "sources": sources,
            "processing_time_ms": processing_time_ms,
        },
    }
