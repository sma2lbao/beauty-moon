"""Tests for security-related settings."""
from app.core.config import Settings


def test_security_settings_defaults():
    settings = Settings()
    assert settings.rate_limit_enabled is True
    assert settings.rate_limit_default_per_minute == 120
    assert settings.rate_limit_qa_per_minute == 30
    assert settings.rate_limit_upload_per_minute == 10
    assert settings.max_json_body_size == 1048576
