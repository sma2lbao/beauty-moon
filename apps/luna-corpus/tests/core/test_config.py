"""Tests for application configuration."""

import pytest
from pydantic import ValidationError

from app.core.config import AppEnv, Settings


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
