"""Request-scoped context for request_id and client IP via contextvars."""
from contextvars import ContextVar

_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)
_client_ip: ContextVar[str | None] = ContextVar("client_ip", default=None)
_user_id: ContextVar[str | None] = ContextVar("user_id", default=None)
_tenant_id: ContextVar[str | None] = ContextVar("tenant_id", default=None)


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


def set_identity_context(user_id: str | None, tenant_id: str | None) -> None:
    """Store the authenticated user_id and tenant_id for the request scope."""
    _user_id.set(user_id)
    _tenant_id.set(tenant_id)


def get_user_id() -> str | None:
    """Return the current user_id, or None if unset."""
    return _user_id.get()


def get_tenant_id() -> str | None:
    """Return the current tenant_id, or None if unset."""
    return _tenant_id.get()


def reset_request_context() -> None:
    """Clear the request context (request_id, client IP, identity)."""
    _request_id.set(None)
    _client_ip.set(None)
    _user_id.set(None)
    _tenant_id.set(None)
