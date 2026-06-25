"""Integration tests for file upload endpoints."""
import io
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.auth import require_permission
from app.auth.permissions import PermissionSlug
from app.db.database import get_db
from app.db.models import (
    Base,
    FileUpload,
    FileUploadStatus,
    KnowledgeBase,
    Permission,
    Role,
    Tenant,
    User,
    Workspace,
    WorkspaceMembership,
)
from app.main import create_app


@pytest.fixture
def app_db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    tenant = Tenant(name="Acme", slug="acme")
    workspace = Workspace(name="Research", slug="research", tenant=tenant)
    kb_one = KnowledgeBase(name="Docs", slug="docs", workspace=workspace)
    session.add_all([kb_one])
    session.commit()

    context = {
        "tenant_id": tenant.id,
        "workspace_id": workspace.id,
        "kb_one_id": kb_one.id,
    }
    session.close()

    yield engine, Session, context
    engine.dispose()


@pytest.fixture
def client(app_db):
    engine, Session, _ = app_db

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


def create_user_with_permissions(Session, workspace_id, label, permission_slugs):
    session = Session()
    try:
        user = User(email=f"{label}@example.com", display_name=label)
        permissions = []
        for slug in permission_slugs:
            permission = (
                session.query(Permission).filter(Permission.slug == slug).first()
            )
            if not permission:
                permission = Permission(name=slug, slug=slug, description=slug)
            permissions.append(permission)
        role = Role(
            name=label, slug=label, is_system=True, permissions=permissions
        )
        membership = WorkspaceMembership(
            user=user, workspace_id=workspace_id, roles=[role]
        )
        session.add(membership)
        session.commit()
        return user.id
    finally:
        session.close()


def _auth_headers(context, knowledge_base_id="kb-1", user_id="user-1"):
    return {
        "X-User-Id": user_id,
        "X-Tenant-Id": context["tenant_id"],
        "X-Workspace-Id": context["workspace_id"],
        "X-Knowledge-Base-Id": knowledge_base_id,
    }


@patch("app.api.routes.get_storage_backend")
@patch("app.api.routes.get_parser_registry")
@patch("app.api.routes.DocumentProcessor")
def test_upload_file_success(mock_processor, mock_registry, mock_storage, client, app_db):
    """Test successful file upload."""
    _, Session, context = app_db
    user_id = create_user_with_permissions(
        Session,
        context["workspace_id"],
        "file_uploader",
        [PermissionSlug.DOCUMENT_WRITE],
    )

    # Setup mocks
    storage = mock_storage.return_value
    async def mock_save(f, p):
        return p
    storage.save = mock_save

    registry = mock_registry.return_value
    registry.is_supported.return_value = True
    parser = type("Parser", (), {"parse": lambda self, c, n: "Parsed text"})()
    registry.get_parser.return_value = parser

    mock_processor.return_value.process_document.return_value = []

    response = client.post(
        "/api/v1/files/upload",
        headers=_auth_headers(context, context["kb_one_id"], user_id),
        files={"file": ("test.txt", io.BytesIO(b"Hello"), "text/plain")},
    )

    assert response.status_code == 201
    data = response.json()
    assert data["file"]["original_name"] == "test.txt"
    assert data["file"]["mime_type"] == "text/plain"


@patch("app.api.routes.get_storage_backend")
@patch("app.api.routes.get_parser_registry")
def test_upload_file_unsupported_type(mock_registry, mock_storage, client, app_db):
    """Test upload with unsupported file type."""
    _, Session, context = app_db
    user_id = create_user_with_permissions(
        Session,
        context["workspace_id"],
        "file_uploader",
        [PermissionSlug.DOCUMENT_WRITE],
    )

    registry = mock_registry.return_value
    registry.is_supported.return_value = False
    registry.list_supported_types.return_value = ["text/plain"]

    response = client.post(
        "/api/v1/files/upload",
        headers=_auth_headers(context, context["kb_one_id"], user_id),
        files={"file": ("test.unknown", io.BytesIO(b"data"), "application/unknown")},
    )

    assert response.status_code == 415


def test_list_files_requires_auth(client):
    """Test list files requires authentication."""
    response = client.get("/api/v1/files")
    assert response.status_code == 400


def test_delete_file_requires_auth(client):
    """Test delete file requires authentication."""
    response = client.delete("/api/v1/files/file-1")
    assert response.status_code == 400
