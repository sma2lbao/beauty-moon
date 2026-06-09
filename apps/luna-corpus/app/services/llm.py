"""Ollama LLM and embeddings integration."""
from typing import Any

from langchain_ollama import ChatOllama, OllamaEmbeddings

from app.core.config import get_settings

settings = get_settings()


def get_chat_model() -> ChatOllama:
    """Get Ollama chat model instance."""
    return ChatOllama(
        base_url=settings.ollama_base_url,
        model=settings.ollama_model,
        temperature=0.7,
        stream=False,
    )


def get_embeddings_model() -> OllamaEmbeddings:
    """Get Ollama embeddings model instance."""
    return OllamaEmbeddings(
        base_url=settings.ollama_base_url,
        model=settings.ollama_embed_model,
    )


def embed_text(text: str) -> list[float]:
    """Generate embedding for a single text.

    Args:
        text: Text to embed

    Returns:
        Embedding vector
    """
    embeddings = get_embeddings_model()
    return embeddings.embed_query(text)


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Generate embeddings for multiple texts.

    Args:
        texts: List of texts to embed

    Returns:
        List of embedding vectors
    """
    embeddings = get_embeddings_model()
    return embeddings.embed_documents(texts)


def generate_response(prompt: str, context: str | None = None) -> str:
    """Generate response from LLM.

    Args:
        prompt: User prompt
        context: Optional context to prepend

    Returns:
        Generated response
    """
    chat = get_chat_model()

    if context:
        full_prompt = f"""Based on the following context, answer the question.

Context:
{context}

Question: {prompt}

Answer:"""
    else:
        full_prompt = prompt

    response = chat.invoke(full_prompt)
    return response.content if hasattr(response, "content") else str(response)


def check_ollama_health() -> bool:
    """Check if Ollama service is healthy.

    Returns:
        True if Ollama is accessible
    """
    try:
        import httpx

        response = httpx.get(f"{settings.ollama_base_url}/api/tags", timeout=5)
        return response.status_code == 200
    except Exception:
        return False
