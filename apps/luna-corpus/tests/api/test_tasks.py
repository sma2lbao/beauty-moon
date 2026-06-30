"""Integration tests for task endpoints."""

from app.auth.permissions import PermissionSlug
from app.db.models import IngestionTask, KnowledgeBase, TaskStatus, TaskType, Workspace
from tests.api.test_file_upload import _auth_headers, create_user_with_permissions


def test_list_tasks_requires_auth(client):
    """Test list tasks requires authentication."""
    response = client.get("/api/v1/tasks")
    assert response.status_code == 400


def test_get_task_requires_auth(client):
    """Test get task requires authentication."""
    response = client.get("/api/v1/tasks/task-1")
    assert response.status_code == 400


def test_list_tasks_empty(client, app_db):
    """Test listing tasks with no tasks returns empty list."""
    _, Session, context = app_db
    user_id = create_user_with_permissions(
        Session,
        context["workspace_id"],
        "task_reader",
        [PermissionSlug.DOCUMENT_READ],
    )

    response = client.get(
        "/api/v1/tasks",
        headers=_auth_headers(context, context["kb_one_id"], user_id),
    )

    assert response.status_code == 200
    data = response.json()
    assert data["tasks"] == []
    assert data["total"] == 0


def test_list_tasks_with_filter(client, app_db):
    """Test listing tasks with status filter."""
    _, Session, context = app_db
    user_id = create_user_with_permissions(
        Session,
        context["workspace_id"],
        "task_reader",
        [PermissionSlug.DOCUMENT_READ],
    )

    # Create a task directly
    session = Session()
    task = IngestionTask(
        type=TaskType.DOCUMENT_INDEX,
        status=TaskStatus.COMPLETED,
        target_id="doc-1",
        knowledge_base_id=context["kb_one_id"],
    )
    session.add(task)
    session.commit()
    session.close()

    response = client.get(
        "/api/v1/tasks?status_filter=completed",
        headers=_auth_headers(context, context["kb_one_id"], user_id),
    )

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert data["tasks"][0]["status"] == "completed"


def test_get_task_not_found(client, app_db):
    """Test getting a non-existent task."""
    _, Session, context = app_db
    user_id = create_user_with_permissions(
        Session,
        context["workspace_id"],
        "task_reader",
        [PermissionSlug.DOCUMENT_READ],
    )

    response = client.get(
        "/api/v1/tasks/nonexistent",
        headers=_auth_headers(context, context["kb_one_id"], user_id),
    )

    assert response.status_code == 404


def test_get_task_cross_kb_404(client, app_db):
    """Test getting a task from different knowledge base returns 404."""
    _, Session, context = app_db

    # Create another KB (must flush to get the generated ID)
    session = Session()
    workspace = (
        session.query(Workspace).filter(Workspace.id == context["workspace_id"]).first()
    )
    kb_two = KnowledgeBase(name="Other", slug="other", workspace=workspace)
    session.add(kb_two)
    session.flush()

    task = IngestionTask(
        type=TaskType.DOCUMENT_INDEX,
        status=TaskStatus.PENDING,
        target_id="doc-1",
        knowledge_base_id=kb_two.id,
    )
    session.add(task)
    session.commit()
    task_id = task.id
    session.close()

    user_id = create_user_with_permissions(
        Session,
        context["workspace_id"],
        "task_reader",
        [PermissionSlug.DOCUMENT_READ],
    )

    response = client.get(
        f"/api/v1/tasks/{task_id}",
        headers=_auth_headers(context, context["kb_one_id"], user_id),
    )

    assert response.status_code == 404
