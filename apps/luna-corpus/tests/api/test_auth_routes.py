"""Integration tests for /api/v1/auth endpoints."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth.password import hash_password
from app.db.database import get_db
from app.db.models import Base, User
from app.main import create_app


@pytest.fixture
def client_and_session():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    session.add(
        User(
            email="login@example.com",
            display_name="Login",
            hashed_password=hash_password("pw12345"),
        )
    )
    session.commit()
    session.close()

    def override_get_db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app = create_app()
    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_login_success(client_and_session):
    resp = client_and_session.post(
        "/api/v1/auth/login",
        json={"email": "login@example.com", "password": "pw12345"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["access_token"] and body["refresh_token"]
    assert body["token_type"] == "bearer"


def test_login_wrong_password(client_and_session):
    resp = client_and_session.post(
        "/api/v1/auth/login",
        json={"email": "login@example.com", "password": "nope"},
    )
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Invalid credentials"


def test_me_with_access_token(client_and_session):
    login = client_and_session.post(
        "/api/v1/auth/login",
        json={"email": "login@example.com", "password": "pw12345"},
    ).json()
    resp = client_and_session.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {login['access_token']}"},
    )
    assert resp.status_code == 200
    assert resp.json()["email"] == "login@example.com"


def test_refresh_rotates(client_and_session):
    login = client_and_session.post(
        "/api/v1/auth/login",
        json={"email": "login@example.com", "password": "pw12345"},
    ).json()
    resp = client_and_session.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": login["refresh_token"]},
    )
    assert resp.status_code == 200
    assert resp.json()["refresh_token"] != login["refresh_token"]


def test_logout_then_refresh_rejected(client_and_session):
    login = client_and_session.post(
        "/api/v1/auth/login",
        json={"email": "login@example.com", "password": "pw12345"},
    ).json()
    client_and_session.post(
        "/api/v1/auth/logout", json={"refresh_token": login["refresh_token"]}
    )
    resp = client_and_session.post(
        "/api/v1/auth/refresh", json={"refresh_token": login["refresh_token"]}
    )
    assert resp.status_code == 401
