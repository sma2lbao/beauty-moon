"""Core configuration for luna-corpus."""
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class LLMProvider(StrEnum):
    """Available LLM providers."""

    OLLAMA = "ollama"
    ARK = "ark"
    DOUBAO = "doubao"


class AgentMode(StrEnum):
    """Agent execution modes."""

    DIRECT = "direct"
    REACT = "react"
    PLAN = "plan"
    LANGGRAPH = "langgraph"


class AppEnv(StrEnum):
    """Application runtime environments."""

    DEVELOPMENT = "development"
    TEST = "test"
    PRODUCTION = "production"


class VectorStoreBackendType(StrEnum):
    """Available vector store backends."""

    CHROMA_LOCAL = "chroma_local"
    CHROMA_SERVER = "chroma_server"


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # Database
    database_url: str = Field(
        default="mysql+mysqlconnector://user:password@localhost:3306/luna_corpus",
        description="MySQL database connection URL",
    )

    # Vector Store / Chroma
    vectorstore_backend: VectorStoreBackendType = Field(
        default=VectorStoreBackendType.CHROMA_LOCAL,
        description="Vector store backend to use",
    )
    chroma_collection_name: str = Field(
        default="document_chunks",
        description="Chroma collection name for document chunks",
    )
    chroma_data_dir: Path = Field(
        default=Path("./data/chroma"),
        description="Directory for local Chroma vector store data",
    )
    chroma_host: str = Field(
        default="localhost",
        description="Chroma server host",
    )
    chroma_port: int = Field(
        default=8000,
        description="Chroma server port",
    )
    chroma_ssl: bool = Field(
        default=False,
        description="Use SSL when connecting to Chroma server",
    )
    chroma_auth_token: str = Field(
        default="",
        description="Optional bearer token for Chroma server",
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

    # Runtime Environment
    app_env: AppEnv = Field(
        default=AppEnv.DEVELOPMENT,
        description="Application runtime environment",
    )
    auto_create_tables: bool = Field(
        default=False,
        description="Automatically create database tables on startup",
    )
    cors_allow_origins: list[str] = Field(
        default_factory=list,
        description="Allowed CORS origins",
    )

    # RAG
    retrieval_top_k: int = Field(default=5, description="Number of chunks to retrieve")

    # Conversation Memory
    conversation_memory_window: int = Field(
        default=10, description="Number of recent messages to include in context"
    )
    conversation_max_tokens: int = Field(
        default=4000, description="Maximum tokens allocated for conversation history"
    )
    conversation_summarize_threshold: int = Field(
        default=20, description="Message count before triggering summarization"
    )

    # Agent
    agent_default_mode: str = Field(
        default="direct", description="Default agent mode"
    )
    agent_max_steps: int = Field(
        default=10, description="Maximum steps for agent execution"
    )
    agent_react_max_iterations: int = Field(
        default=5, description="Max iterations for ReAct agent"
    )
    agent_plan_max_steps: int = Field(
        default=10, description="Max steps in a plan"
    )

    @field_validator("cors_allow_origins", mode="before")
    @classmethod
    def parse_cors_allow_origins(cls, value: Any) -> list[str]:
        if value is None or value == "":
            return []
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        if isinstance(value, list):
            return value
        raise TypeError("CORS_ALLOW_ORIGINS must be a comma-separated string or list")

    @model_validator(mode="after")
    def validate_production_safety(self) -> "Settings":
        if self.app_env != AppEnv.PRODUCTION:
            return self

        if self.auto_create_tables:
            raise ValueError("AUTO_CREATE_TABLES must be false in production")

        if not self.cors_allow_origins:
            raise ValueError("CORS_ALLOW_ORIGINS must be set in production")

        if "*" in self.cors_allow_origins:
            raise ValueError("Production cannot use wildcard CORS origins")

        return self


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
