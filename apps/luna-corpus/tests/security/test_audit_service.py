"""Tests for AuditService."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models import AuditLog, AuditResult, Base
from app.security.audit import AuditAction, AuditService
from app.security.context import reset_request_context, set_request_context


@pytest.fixture
def Session(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    maker = sessionmaker(bind=engine)
    monkeypatch.setattr("app.security.audit.SessionLocal", maker)
    return maker


def test_record_writes_row_with_context(Session):
    set_request_context("req-9", "1.2.3.4")
    db = Session()
    service = AuditService()
    service.record(
        db,
        action=AuditAction.DOCUMENT_CREATE,
        resource_type="document",
        resource_id="doc-1",
        result=AuditResult.SUCCESS,
    )
    db.commit()
    reset_request_context()
    row = db.query(AuditLog).one()
    assert row.action == "document.create"
    assert row.request_id == "req-9"
    assert row.client_ip == "1.2.3.4"
    assert row.result == AuditResult.SUCCESS


def test_record_not_committed_until_caller_commits(Session):
    db = Session()
    AuditService().record(
        db,
        action=AuditAction.DOCUMENT_CREATE,
        resource_type="document",
        resource_id="doc-1",
        result=AuditResult.SUCCESS,
    )
    db.rollback()
    assert db.query(AuditLog).count() == 0


def test_record_failure_survives_independently(Session):
    AuditService().record_failure(
        action=AuditAction.DOCUMENT_DELETE,
        resource_type="document",
        resource_id="doc-x",
        detail="not found",
    )
    verify = Session()
    row = verify.query(AuditLog).one()
    assert row.result == AuditResult.FAILURE
    assert row.detail == "not found"


def test_record_failure_swallows_errors(monkeypatch):
    # SessionLocal raising must not propagate.
    def boom():
        raise RuntimeError("db down")

    monkeypatch.setattr("app.security.audit.SessionLocal", boom)
    AuditService().record_failure(
        action=AuditAction.QA_QUERY,
        resource_type="conversation",
        resource_id=None,
        detail="x",
    )  # must not raise
