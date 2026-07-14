"""Tests for JWT-related settings and production validation."""
import pytest

from app.core.config import AppEnv, Settings


def test_jwt_defaults_present_in_development():
    settings = Settings(app_env=AppEnv.DEVELOPMENT)
    assert settings.jwt_algorithm == "HS256"
    assert settings.access_token_expire_minutes == 15
    assert settings.refresh_token_expire_days == 7
    assert settings.jwt_secret_key  # dev 有默认值


def test_production_requires_jwt_secret():
    with pytest.raises(ValueError, match="JWT_SECRET_KEY"):
        Settings(
            app_env=AppEnv.PRODUCTION,
            auto_create_tables=False,
            cors_allow_origins=["https://app.example.com"],
            jwt_secret_key="",
        )
