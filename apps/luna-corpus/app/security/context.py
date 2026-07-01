"""Request-scoped context for request_id and client IP via contextvars."""
from contextvars import ContextVar

_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)
_client_ip: ContextVar[str | None] = ContextVar("client_ip", default=None)


def set_request_context(request_id: str, client_ip: str | None) -> None:
    """Store request_id and client IP for the current request scope."""
    _request_id.set(request_id)
    _client_ip.set(client_ip)


def get_request_id() -> str | None:
    """Return the current request_id, or None if unset."""
    return _request_id.get()


def get_client_ip() -> str | None:
    """Return the current client IP, or None if unset."""
    return _client_ip.get()


def reset_request_context() -> None:
    """Clear the request context (request_id and client IP)."""
    _request_id.set(None)
    _client_ip.set(None)
