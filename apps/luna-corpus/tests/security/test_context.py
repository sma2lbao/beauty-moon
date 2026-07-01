"""Tests for request-scoped security context."""
from app.security.context import (
    get_client_ip,
    get_request_id,
    reset_request_context,
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
