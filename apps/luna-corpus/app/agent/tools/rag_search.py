"""Knowledge-base scoped RAG search tool."""
from app.agent.tool import Tool, tool
from app.retrieval.hybrid import hybrid_search
from app.services.llm import embed_text


_RAG_SEARCH_PARAMETERS = {
    "type": "object",
    "properties": {
        "query": {
            "type": "string",
            "description": "The search query to find relevant documents",
        },
        "top_k": {
            "type": "integer",
            "description": "Maximum number of documents to return",
            "default": 5,
        },
    },
    "required": ["query"],
}


def _format_rag_results(query: str, knowledge_base_id: str, top_k: int = 5) -> str:
    """Execute scoped RAG search and format results."""
    try:
        query_embedding = embed_text(query)
        results = hybrid_search(
            query,
            query_embedding,
            top_k=top_k,
            knowledge_base_id=knowledge_base_id,
        )

        if not results:
            return "No relevant documents found in the knowledge base."

        formatted = []
        for i, result in enumerate(results, 1):
            content = result.get("content", "") or ""
            score = result.get("score", 0.0)
            doc_id = result.get("document_id", "unknown")
            formatted.append(
                f"[Document {i}] (ID: {doc_id}, Relevance: {score:.3f})\n"
                f"{content[:500]}{'...' if len(content) > 500 else ''}"
            )

        return "\n\n".join(formatted)

    except Exception as e:
        return f"Error searching knowledge base: {str(e)}"


def create_rag_search_tool(knowledge_base_id: str) -> Tool:
    """Create a RAG search tool scoped to one knowledge base."""

    def _get_rag_results(query: str, top_k: int = 5) -> str:
        return _format_rag_results(
            query=query,
            top_k=top_k,
            knowledge_base_id=knowledge_base_id,
        )

    return tool(
        name="rag_search",
        description=(
            "Search the current knowledge base for relevant documents. "
            "Use this when the user asks about information that might be "
            "in the current documents."
        ),
        parameters_schema=_RAG_SEARCH_PARAMETERS,
    )(_get_rag_results)
