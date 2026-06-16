"""LLM and embeddings integration supporting multiple providers."""
import hashlib
import hmac
import time
from typing import Any

from langchain_ollama import ChatOllama, OllamaEmbeddings

from app.core.config import LLMProvider, get_settings

settings = get_settings()


class VolcengineEmbeddings:
    """Volcengine (Doubao) embeddings implementation."""

    def __init__(
        self,
        access_key: str,
        secret_key: str,
        region: str,
        model: str = "doubao-embedding-vision-250615",
    ):
        self.access_key = access_key
        self.secret_key = secret_key
        self.region = region
        self.model = model
        self.service = " volcengine_ml_api"
        self.host = f"open.volcengineapi.com"
        self.endpoint = f"https://{self.host}"

    def _sign(self, key: bytes, msg: str) -> bytes:
        return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()

    def _get_authorization(self, method: str, path: str, params: dict, headers: dict) -> str:
        service = self.service.strip()
        t = time.gmtime()
        timestamp = time.strftime("%Y%m%dT%H%M%SZ", t)
        date = time.strftime("%Y%m%d", t)

        headers["X-Date"] = timestamp
        headers["X-Region"] = self.region
        headers["X-Service"] = service

        sorted_headers = sorted(headers.items(), key=lambda x: x[0].lower())
        signed_headers = ";".join([k.lower() for k, _ in sorted_headers])
        canonical_headers = "\n".join([f"{k.lower()}:{v}" for k, v in sorted_headers]) + "\n"

        sorted_params = sorted(params.items(), key=lambda x: x[0])
        canonical_query = "&".join([f"{k}={v}" for k, v in sorted_params])
        payload_hash = hashlib.sha256(b"").hexdigest()

        canonical_request = f"{method}\n{path}\n{canonical_query}\n{canonical_headers}\n{signed_headers}\n{payload_hash}"
        algorithm = "HMAC-SHA256"
        credential_scope = f"{date}/{service}/request"
        string_to_sign = f"{algorithm}\n{timestamp}\n{credential_scope}\n{hashlib.sha256(canonical_request.encode()).hexdigest()}"

        signature = hmac.new(
            f"HMAC-SHA256\n{date}\n{credential_scope}\n{string_to_sign}".encode(),
            self.secret_key.encode(),
            hashlib.sha256,
        ).hexdigest()

        return f"{algorithm} Credential={self.access_key}/{credential_scope}, SignedHeaders={signed_headers}, Signature={signature}"

    def embed_query(self, text: str) -> list[float]:
        """Generate embedding for a single text query."""
        return self.embed_documents([text])[0]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for multiple texts."""
        import httpx

        path = "/api/v1/embeddings/text_embedding"
        method = "POST"
        headers = {
            "Content-Type": "application/json",
            "Host": self.host,
        }
        params = {}
        body = {"model": self.model, "texts": [{"text": t} for t in texts]}

        authorization = self._get_authorization(method, path, params, headers)
        headers["Authorization"] = authorization

        response = httpx.post(
            f"{self.endpoint}{path}",
            headers=headers,
            json=body,
            timeout=60,
        )
        response.raise_for_status()
        result = response.json()

        return [item["embedding"] for item in result["data"]]


def get_chat_model() -> Any:
    """Get chat model instance based on configured provider."""
    if settings.llm_provider == LLMProvider.ARK:
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=settings.ark_model,
            api_key=settings.ark_api_key,
            base_url="https://ark.cn-beijing.volces.com/api/v3",
            temperature=0.7,
            model_kwargs={"stream": False},
        )
    else:
        return ChatOllama(
            base_url=settings.ollama_base_url,
            model=settings.ollama_model,
            temperature=0.7,
            stream=False,
        )


def get_embeddings_model() -> Any:
    """Get embeddings model instance based on configured provider."""
    if settings.llm_provider == LLMProvider.DOUBAO:
        return VolcengineEmbeddings(
            access_key=settings.volcengine_access_key,
            secret_key=settings.volcengine_secret_key,
            region=settings.volcengine_region,
            model=settings.doubao_embed_model,
        )
    else:
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


async def generate_streaming_response(prompt: str, context: str | None = None):
    """Generate streaming response from LLM.

    Args:
        prompt: User prompt
        context: Optional context to prepend

    Yields:
        Response chunks as they arrive
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

    async for chunk in chat.astream(full_prompt):
        yield chunk.content if hasattr(chunk, "content") else str(chunk)


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


def check_ark_health() -> bool:
    """Check if Ark API is accessible.

    Returns:
        True if Ark API key is configured
    """
    return bool(settings.ark_api_key)


def check_doubao_health() -> bool:
    """Check if Doubao API is accessible.

    Returns:
        True if Volcengine credentials are configured
    """
    return bool(settings.volcengine_access_key and settings.volcengine_secret_key)


def get_provider_status() -> dict[str, Any]:
    """Get status of all LLM providers.

    Returns:
        Dictionary with provider availability
    """
    return {
        "current_provider": settings.llm_provider.value,
        "ollama": {
            "available": check_ollama_health(),
            "base_url": settings.ollama_base_url,
            "model": settings.ollama_model,
            "embed_model": settings.ollama_embed_model,
        },
        "ark": {
            "configured": check_ark_health(),
            "model": settings.ark_model,
        },
        "doubao": {
            "configured": check_doubao_health(),
            "embed_model": settings.doubao_embed_model,
            "region": settings.volcengine_region,
        },
    }
