"""JWT access tokens and opaque refresh token helpers."""
import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt

from app.core.config import get_settings


class TokenError(Exception):
    """Raised when an access token is missing, invalid, or expired."""


def create_access_token(user_id: str) -> str:
    """Sign a short-lived JWT access token carrying the user id as subject."""
    settings = get_settings()
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "iat": now,
        "exp": now + timedelta(minutes=settings.access_token_expire_minutes),
        "type": "access",
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> str:
    """Validate a JWT access token and return the subject (user id)."""
    settings = get_settings()
    try:
        payload = jwt.decode(
            token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm]
        )
    except JWTError as exc:
        raise TokenError("Invalid or expired token") from exc
    sub = payload.get("sub")
    if not sub or payload.get("type") != "access":
        raise TokenError("Malformed token payload")
    return sub


def generate_refresh_token() -> str:
    """Return a cryptographically random opaque refresh token."""
    return secrets.token_urlsafe(48)


def hash_refresh_token(raw: str) -> str:
    """Return the SHA-256 hex digest used to store refresh tokens."""
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
