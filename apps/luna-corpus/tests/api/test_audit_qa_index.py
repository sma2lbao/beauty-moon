"""Audit coverage for QA query and background index task."""
from unittest.mock import patch

from app.auth.permissions import PermissionSlug
from app.db.models import AuditLog, AuditResult
from tests.api.test_file_upload import (  # noqa: F401
    _auth_headers,
    create_user_with_permissions,
)


@patch("app.api.routes.answer_question")
def test_qa_query_writes_audit(mock_answer, client, app_db):
    mock_answer.return_value = {
        "answer": "hi",
        "sources": [],
        "processing_time_ms": 5,
    }
    _, Session, context = app_db
    user_id = create_user_with_permissions(
        Session,
        context["workspace_id"],
        "asker",
        [PermissionSlug.QA_QUERY, PermissionSlug.WORKSPACE_READ,
         PermissionSlug.KNOWLEDGE_BASE_READ],
    )
    headers = _auth_headers(
        context, knowledge_base_id=context["kb_one_id"], user_id=user_id
    )
    resp = client.post("/api/v1/qa/query", json={"question": "what?"}, headers=headers)
    assert resp.status_code == 200
    session = Session()
    row = session.query(AuditLog).filter(AuditLog.action == "qa.query").one()
    assert row.result == AuditResult.SUCCESS
    assert row.actor_user_id == user_id


def test_index_task_writes_success_audit(app_db, monkeypatch):
    engine, Session, context = app_db
    monkeypatch.setattr("app.api.routes.SessionLocal", Session)

    from app.api.routes import _run_index_task
    from app.db.models import Document

    session = Session()
    doc = Document(title="d", content="c", knowledge_base_id=context["kb_one_id"])
    session.add(doc)
    session.commit()
    doc_id = doc.id

    with patch("app.services.document_processor.DocumentProcessor") as proc, \
         patch("app.api.routes.TaskService") as task_service:
        proc.return_value.process_document.return_value = None
        task_service.return_value.mark_running.return_value = None
        task_service.return_value.mark_completed.return_value = None
        _run_index_task("task-1", doc_id)

    verify = Session()
    row = (
        verify.query(AuditLog)
        .filter(AuditLog.action == "document.index")
        .one()
    )
    assert row.result == AuditResult.SUCCESS
    assert row.resource_id == doc_id
