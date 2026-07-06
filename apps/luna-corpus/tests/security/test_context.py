"""Tests for request-scoped security context."""
from app.security.context import (
    get_client_ip,
    get_request_id,
    get_tenant_id,
    get_user_id,
    reset_request_context,
    set_identity_context,
    set_request_context,
)


def test_set_and_get_context():
    set_request_context("req-123", "10.0.0.1")
    assert get_request_id() == "req-123"
    assert get_client_ip() == "10.0.0.1"


def test_reset_clears_context():
    set_request_context("req-123", "10.0.0.1")
    reset_request_context()
    assert get_request_id() is None
    assert get_client_ip() is None


def test_defaults_are_none():
    reset_request_context()
    assert get_request_id() is None
    assert get_client_ip() is None


def test_identity_context_roundtrip():
    set_identity_context("user-1", "tenant-1")
    assert get_user_id() == "user-1"
    assert get_tenant_id() == "tenant-1"
    reset_request_context()
    assert get_user_id() is None
    assert get_tenant_id() is None


def test_identity_defaults_none():
    reset_request_context()
    assert get_user_id() is None
    assert get_tenant_id() is None
