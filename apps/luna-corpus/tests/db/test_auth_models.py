"""Tests for auth-related model columns and RefreshToken table."""
from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models import Base, RefreshToken, User


def _session():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def test_user_has_hashed_password_column():
    session = _session()
    user = User(email="a@example.com", display_name="A", hashed_password="hashed")
    session.add(user)
    session.commit()
    assert session.query(User).first().hashed_password == "hashed"


def test_refresh_token_persist_and_revoke():
    session = _session()
    user = User(email="b@example.com", display_name="B", hashed_password="h")
    session.add(user)
    session.commit()
    rt = RefreshToken(
        user_id=user.id,
        token_hash="deadbeef",
        expires_at=datetime.utcnow() + timedelta(days=7),
    )
    session.add(rt)
    session.commit()
    stored = session.query(RefreshToken).first()
    assert stored.revoked_at is None
    assert stored.user_id == user.id
