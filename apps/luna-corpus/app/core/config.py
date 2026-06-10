"""Core configuration for luna-corpus."""
from enum import Enum
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class LLMProvider(str, Enum):
    """Available LLM providers."""

    OLLAMA = "ollama"
    DEEPSEEK = "deepseek"


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
        description="LLM provider to use (ollama or deepseek)",
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

    # DeepSeek
    deepseek_api_key: str = Field(
        default="",
        description="DeepSeek API key",
    )
    deepseek_model: str = Field(
        default="deepseek-chat",
        description="DeepSeek model name (e.g., deepseek-chat, deepseek-coder)",
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
