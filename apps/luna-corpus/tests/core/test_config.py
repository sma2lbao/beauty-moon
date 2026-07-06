"""Tests for application configuration."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config import AppEnv, LogFormat, Settings, VectorStoreBackendType


def test_default_environment_settings():
    settings = Settings()

    assert settings.app_env == AppEnv.DEVELOPMENT
    assert settings.auto_create_tables is False
    assert settings.cors_allow_origins == []


def test_cors_origins_parse_comma_separated_string():
    settings = Settings(
        cors_allow_origins="http://localhost:3000,http://localhost:4200",
    )

    assert settings.cors_allow_origins == [
        "http://localhost:3000",
        "http://localhost:4200",
    ]


def test_cors_origins_trim_whitespace_and_ignore_empty_values():
    settings = Settings(
        cors_allow_origins=" http://localhost:3000, ,http://localhost:4200 ",
    )

    assert settings.cors_allow_origins == [
        "http://localhost:3000",
        "http://localhost:4200",
    ]


def test_development_allows_auto_create_tables():
    settings = Settings(
        app_env=AppEnv.DEVELOPMENT,
        auto_create_tables=True,
    )

    assert settings.auto_create_tables is True


def test_production_rejects_auto_create_tables():
    with pytest.raises(ValidationError, match="AUTO_CREATE_TABLES must be false"):
        Settings(
            app_env=AppEnv.PRODUCTION,
            auto_create_tables=True,
            cors_allow_origins="https://app.example.com",
        )


def test_production_rejects_empty_cors_origins():
    with pytest.raises(ValidationError, match="CORS_ALLOW_ORIGINS must be set"):
        Settings(app_env=AppEnv.PRODUCTION)


def test_production_rejects_wildcard_cors_origin():
    with pytest.raises(ValidationError, match="wildcard CORS origins"):
        Settings(
            app_env=AppEnv.PRODUCTION,
            cors_allow_origins="*",
        )


def test_production_accepts_explicit_cors_origin():
    settings = Settings(
        app_env=AppEnv.PRODUCTION,
        cors_allow_origins="https://app.example.com",
    )

    assert settings.cors_allow_origins == ["https://app.example.com"]


def test_vectorstore_defaults_to_local_chroma():
    settings = Settings()

    assert settings.vectorstore_backend == VectorStoreBackendType.CHROMA_LOCAL
    assert settings.chroma_collection_name == "document_chunks"
    assert settings.chroma_host == "localhost"
    assert settings.chroma_port == 8000
    assert settings.chroma_ssl is False
    assert settings.chroma_auth_token == ""


def test_vectorstore_backend_accepts_chroma_server():
    settings = Settings(
        vectorstore_backend="chroma_server",
        chroma_host="chroma.example.com",
        chroma_port=8443,
        chroma_ssl=True,
        chroma_auth_token="secret-token",
    )

    assert settings.vectorstore_backend == VectorStoreBackendType.CHROMA_SERVER
    assert settings.chroma_host == "chroma.example.com"
    assert settings.chroma_port == 8443
    assert settings.chroma_ssl is True
    assert settings.chroma_auth_token == "secret-token"


def test_default_storage_config():
    """Test default storage configuration values."""
    from app.core.config import Settings

    settings = Settings()
    assert settings.storage_backend == "local"
    assert settings.storage_local_path == Path("data/uploads")
    assert settings.max_upload_size == 52428800
    assert settings.upload_duplicate_policy == "reject"


def test_custom_storage_config():
    """Test custom storage configuration."""
    from app.core.config import Settings

    settings = Settings(
        storage_backend="s3",
        storage_local_path="/tmp/uploads",
        max_upload_size=10485760,
        upload_duplicate_policy="replace",
    )
    assert settings.storage_backend == "s3"
    assert settings.storage_local_path == Path("/tmp/uploads")
    assert settings.max_upload_size == 10485760
    assert settings.upload_duplicate_policy == "replace"


def test_log_format_defaults_to_json_in_production():
    s = Settings(app_env=AppEnv.PRODUCTION, database_url="sqlite://",
                 cors_allow_origins="https://app.example.com")
    assert s.log_format == LogFormat.JSON


def test_log_format_defaults_to_console_in_development():
    s = Settings(app_env=AppEnv.DEVELOPMENT, database_url="sqlite://")
    assert s.log_format == LogFormat.CONSOLE


def test_metrics_enabled_defaults_true():
    s = Settings(database_url="sqlite://")
    assert s.metrics_enabled is True
    assert s.log_level == "INFO"


def test_explicit_log_format_overrides_env_default():
    s = Settings(app_env=AppEnv.PRODUCTION, log_format=LogFormat.CONSOLE,
                 database_url="sqlite://",
                 cors_allow_origins="https://app.example.com")
    assert s.log_format == LogFormat.CONSOLE


def test_retrieval_mode_defaults_to_hybrid():
    from app.core.config import RetrievalMode, Settings

    settings = Settings()
    assert settings.retrieval_mode == RetrievalMode.HYBRID
    assert settings.retrieval_candidate_k == 20
    assert settings.rrf_k == 60
    assert settings.bm25_cache_ttl_seconds == 600


def test_retrieval_mode_can_be_set_to_vector():
    from app.core.config import RetrievalMode, Settings

    settings = Settings(retrieval_mode="vector")
    assert settings.retrieval_mode == RetrievalMode.VECTOR
