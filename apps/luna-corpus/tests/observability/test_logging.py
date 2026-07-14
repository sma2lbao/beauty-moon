"""Structured logging configuration tests."""
import json
import logging

from app.core.config import AppEnv, LogFormat, Settings
from app.observability.logging import (
    bind_request_context,
    configure_logging,
    get_logger,
)
from app.security.context import reset_request_context, set_identity_context


def test_bind_request_context_injects_identity():
    reset_request_context()
    set_identity_context("user-9", "tenant-9")
    event = bind_request_context(None, "info", {"event": "hi"})
    assert event["user_id"] == "user-9"
    assert event["tenant_id"] == "tenant-9"
    reset_request_context()


def test_bind_request_context_omits_unset_fields():
    reset_request_context()
    event = bind_request_context(None, "info", {"event": "hi"})
    assert "user_id" not in event
    assert "tenant_id" not in event


def test_json_logging_emits_json(capsys):
    settings = Settings(app_env=AppEnv.PRODUCTION, log_format=LogFormat.JSON,
                        database_url="sqlite://",
                        cors_allow_origins=["https://example.com"],
                        jwt_secret_key="prod-secure-secret")
    configure_logging(settings)
    reset_request_context()
    set_identity_context("user-1", "tenant-1")
    get_logger("test").info("request_done", status=200)
    reset_request_context()

    out = capsys.readouterr().out.strip().splitlines()[-1]
    payload = json.loads(out)
    assert payload["event"] == "request_done"
    assert payload["status"] == 200
    assert payload["user_id"] == "user-1"


def test_stdlib_logging_bridged(capsys):
    settings = Settings(app_env=AppEnv.PRODUCTION, log_format=LogFormat.JSON,
                        database_url="sqlite://",
                        cors_allow_origins=["https://example.com"],
                        jwt_secret_key="prod-secure-secret")
    configure_logging(settings)
    logging.getLogger("uvicorn.error").warning("bridged message")
    out = capsys.readouterr().out
    assert "bridged message" in out
