"""Core configuration for luna-corpus."""
from enum import Enum
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class LLMProvider(str, Enum):
    """Available LLM providers."""

    OLLAMA = "ollama"
    ARK = "ark"
    DOUBAO = "doubao"


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # Database
    database_url: str = Field(
        default="mysql+mysqlconnector://user:password@localhost:3306/luna_corpus",
        description="MySQL database connection URL",
    )

    # Chroma
    chroma_data_dir: Path = Field(
        default=Path("./data/chroma"),
        description="Directory for Chroma vector store data",
    )

    # LLM Provider
    llm_provider: LLMProvider = Field(
        default=LLMProvider.OLLAMA,
        description="LLM provider to use (ollama or ark)",
    )

    # Ollama
    ollama_base_url: str = Field(
        default="http://localhost:11434",
        description="Ollama API base URL",
    )
    ollama_model: str = Field(
        default="llama3.1",
        description="Ollama model name for chat",
    )
    ollama_embed_model: str = Field(
        default="nomic-embed-text",
        description="Ollama model name for embeddings",
    )

    # Ark
    ark_api_key: str = Field(
        default="",
        description="Ark API key",
    )
    ark_model: str = Field(
        default="deepseek-v4-pro-260425",
        description="Ark model name (e.g., doubao-pro-32k, doubao-lite-32k)",
    )

    # Doubao (Volcengine)
    volcengine_access_key: str = Field(
        default="",
        description="Volcengine Access Key for Doubao embeddings",
    )
    volcengine_secret_key: str = Field(
        default="",
        description="Volcengine Secret Key for Doubao embeddings",
    )
    volcengine_region: str = Field(
        default="cn-beijing",
        description="Volcengine region",
    )
    doubao_embed_model: str = Field(
        default="doubao-embedding-vision-250615",
        description="Doubao embedding model name",
    )

    # API
    api_host: str = Field(default="0.0.0.0")
    api_port: int = Field(default=8000)

    # RAG
    retrieval_top_k: int = Field(default=5, description="Number of chunks to retrieve")


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
