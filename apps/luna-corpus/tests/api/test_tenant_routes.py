"""Tests for tenant structure API routes."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.database import get_db
from app.db.models import Base
from app.main import create_app


@pytest.fixture
def client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)

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
    engine.dispose()


def test_create_and_list_tenant(client):
    response = client.post(
        "/api/v1/tenants",
        json={"name": "Acme", "slug": "acme"},
    )

    assert response.status_code == 201
    tenant = response.json()
    assert tenant["id"]
    assert tenant["name"] == "Acme"
    assert tenant["slug"] == "acme"

    response = client.get("/api/v1/tenants")

    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert response.json()["tenants"][0]["id"] == tenant["id"]


def test_create_and_list_workspace(client):
    tenant = client.post(
        "/api/v1/tenants",
        json={"name": "Acme", "slug": "acme"},
    ).json()

    response = client.post(
        "/api/v1/workspaces",
        json={"tenant_id": tenant["id"], "name": "Research", "slug": "research"},
    )

    assert response.status_code == 201
    workspace = response.json()
    assert workspace["tenant_id"] == tenant["id"]

    response = client.get(f"/api/v1/workspaces?tenant_id={tenant['id']}")

    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert response.json()["workspaces"][0]["id"] == workspace["id"]


def test_create_and_list_knowledge_base(client):
    tenant = client.post(
        "/api/v1/tenants",
        json={"name": "Acme", "slug": "acme"},
    ).json()
    workspace = client.post(
        "/api/v1/workspaces",
        json={"tenant_id": tenant["id"], "name": "Research", "slug": "research"},
    ).json()

    response = client.post(
        "/api/v1/knowledge-bases",
        json={
            "workspace_id": workspace["id"],
            "name": "Docs",
            "slug": "docs",
            "description": "Product docs",
        },
    )

    assert response.status_code == 201
    knowledge_base = response.json()
    assert knowledge_base["workspace_id"] == workspace["id"]
    assert knowledge_base["description"] == "Product docs"

    response = client.get(f"/api/v1/knowledge-bases?workspace_id={workspace['id']}")

    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert response.json()["knowledge_bases"][0]["id"] == knowledge_base["id"]
