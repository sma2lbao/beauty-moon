"""Tests for authentication service logic."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth.password import hash_password
from app.auth.service import (
    AuthError,
    authenticate,
    issue_token_pair,
    revoke_refresh_token,
    rotate_refresh_token,
)
from app.db.models import Base, RefreshToken, User


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    user = User(
        email="u@example.com",
        display_name="U",
        hashed_password=hash_password("correct-pw"),
    )
    session.add(user)
    session.commit()
    yield session, user
    session.close()


def test_authenticate_success(db):
    session, user = db
    assert authenticate(session, "u@example.com", "correct-pw").id == user.id


def test_authenticate_wrong_password(db):
    session, _ = db
    with pytest.raises(AuthError):
        authenticate(session, "u@example.com", "wrong")


def test_authenticate_unknown_email(db):
    session, _ = db
    with pytest.raises(AuthError):
        authenticate(session, "nobody@example.com", "correct-pw")


def test_authenticate_unknown_email_runs_dummy_verify(db, monkeypatch):
    """Unknown email must still call verify_password (constant-time defense)."""
    import app.auth.service as service

    calls = []
    real_verify = service.verify_password

    def spy(raw, hashed):
        calls.append(hashed)
        return real_verify(raw, hashed)

    monkeypatch.setattr(service, "verify_password", spy)
    session, _ = db
    with pytest.raises(AuthError):
        authenticate(session, "nobody@example.com", "whatever")
    # verify_password was invoked against the dummy hash, not skipped.
    assert calls == [service._DUMMY_PASSWORD_HASH]


def test_issue_and_rotate(db):
    session, user = db
    pair = issue_token_pair(session, user)
    assert pair.access_token and pair.refresh_token
    assert session.query(RefreshToken).filter_by(revoked_at=None).count() == 1

    new_pair = rotate_refresh_token(session, pair.refresh_token)
    assert new_pair.refresh_token != pair.refresh_token
    # 旧 refresh 已被撤销，不能再次轮换
    with pytest.raises(AuthError):
        rotate_refresh_token(session, pair.refresh_token)


def test_revoke(db):
    session, user = db
    pair = issue_token_pair(session, user)
    revoke_refresh_token(session, pair.refresh_token)
    with pytest.raises(AuthError):
        rotate_refresh_token(session, pair.refresh_token)
