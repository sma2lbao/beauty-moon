"""Tests for the AuditLog model."""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models import AuditLog, AuditResult, Base


def _session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def test_audit_log_persists_all_fields():
    session = _session()
    log = AuditLog(
        actor_user_id="user-1",
        tenant_id="t-1",
        workspace_id="w-1",
        knowledge_base_id="kb-1",
        action="document.create",
        resource_type="document",
        resource_id="doc-1",
        result=AuditResult.SUCCESS,
        detail=None,
        request_id="req-1",
        client_ip="10.0.0.1",
    )
    session.add(log)
    session.commit()
    session.refresh(log)
    assert log.id is not None
    assert log.created_at is not None
    assert log.result == AuditResult.SUCCESS


def test_audit_log_nullable_actor_and_resource():
    session = _session()
    log = AuditLog(
        action="qa.query",
        resource_type="conversation",
        result=AuditResult.FAILURE,
        detail="boom",
    )
    session.add(log)
    session.commit()
    session.refresh(log)
    assert log.actor_user_id is None
    assert log.resource_id is None
