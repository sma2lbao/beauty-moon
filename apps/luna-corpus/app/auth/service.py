"""Authentication business logic: login, token issuance, rotation, revocation."""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.auth.password import hash_password, verify_password
from app.auth.tokens import (
    create_access_token,
    generate_refresh_token,
    hash_refresh_token,
)
from app.core.config import get_settings
from app.db.models import RefreshToken, User


class AuthError(Exception):
    """Raised on failed authentication or invalid refresh token."""


# Precomputed hash used to keep authentication timing constant when the email
# does not exist, preventing user-enumeration via response-time side channel.
_DUMMY_PASSWORD_HASH = hash_password("dummy-password-never-matches")


@dataclass(frozen=True)
class TokenPair:
    access_token: str
    refresh_token: str
    expires_in: int


def authenticate(db: Session, email: str, password: str) -> User:
    """Return the user if email+password match and the account is active."""
    user = db.query(User).filter(User.email == email).first()
    if not user or not user.hashed_password:
        # Run a verify against a dummy hash so the response time matches the
        # existing-user path and does not leak whether the email is registered.
        verify_password(password, _DUMMY_PASSWORD_HASH)
        raise AuthError("Invalid credentials")
    if not verify_password(password, user.hashed_password):
        raise AuthError("Invalid credentials")
    if not user.is_active:
        raise AuthError("Invalid credentials")
    return user


def issue_token_pair(db: Session, user: User) -> TokenPair:
    """Create a new access token and persist a fresh refresh token record."""
    settings = get_settings()
    raw_refresh = generate_refresh_token()
    record = RefreshToken(
        user_id=user.id,
        token_hash=hash_refresh_token(raw_refresh),
        expires_at=datetime.now(timezone.utc)
        + timedelta(days=settings.refresh_token_expire_days),
    )
    db.add(record)
    db.commit()
    return TokenPair(
        access_token=create_access_token(user.id),
        refresh_token=raw_refresh,
        expires_in=settings.access_token_expire_minutes * 60,
    )


def _load_valid_refresh(db: Session, raw_refresh: str) -> RefreshToken:
    record = (
        db.query(RefreshToken)
        .filter(RefreshToken.token_hash == hash_refresh_token(raw_refresh))
        .first()
    )
    if not record or record.revoked_at is not None:
        raise AuthError("Invalid refresh token")
    expires_at = record.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at < datetime.now(timezone.utc):
        raise AuthError("Invalid refresh token")
    return record


def rotate_refresh_token(db: Session, raw_refresh: str) -> TokenPair:
    """Revoke the presented refresh token and issue a new token pair."""
    record = _load_valid_refresh(db, raw_refresh)
    record.revoked_at = datetime.now(timezone.utc)
    db.commit()
    user = db.query(User).filter(User.id == record.user_id).first()
    if not user or not user.is_active:
        raise AuthError("Invalid refresh token")
    return issue_token_pair(db, user)


def revoke_refresh_token(db: Session, raw_refresh: str) -> None:
    """Mark the presented refresh token as revoked (logout)."""
    record = _load_valid_refresh(db, raw_refresh)
    record.revoked_at = datetime.now(timezone.utc)
    db.commit()
