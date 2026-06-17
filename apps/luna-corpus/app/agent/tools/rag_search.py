"""RAG search tool - wraps existing vector store."""
from app.agent.tool import tool
from app.db.vectorstore import search_vectorstore
from app.services.llm import embed_text


def _get_rag_results(query: str, top_k: int = 5) -> str:
    """Execute RAG search and format results.

    Args:
        query: Search query
        top_k: Number of results to return

    Returns:
        Formatted search results
    """
    try:
        # Generate query embedding
        query_embedding = embed_text(query)

        # Search vector store
        results = search_vectorstore(query_embedding, top_k=top_k)

        if not results:
            return "No relevant documents found in the knowledge base."

        # Format results
        formatted = []
        for i, result in enumerate(results, 1):
            content = result.get("content", "")
            score = result.get("score", 0.0)
            doc_id = result.get("document_id", "unknown")
            formatted.append(
                f"[Document {i}] (ID: {doc_id}, Relevance: {score:.3f})\n"
                f"{content[:500]}{'...' if len(content) > 500 else ''}"
            )

        return "\n\n".join(formatted)

    except Exception as e:
        return f"Error searching knowledge base: {str(e)}"


rag_search_tool = tool(
    name="rag_search",
    description=(
        "Search the knowledge base for relevant documents. "
        "Use this when the user asks about information that might be "
        "in your documents."
    ),
    parameters_schema={
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
    },
)(_get_rag_results)
