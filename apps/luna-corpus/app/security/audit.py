"""Audit logging service and action vocabulary."""
import enum
import logging

from sqlalchemy.orm import Session

from app.db.database import SessionLocal
from app.db.models import AuditLog, AuditResult
from app.security.context import get_client_ip, get_request_id

logger = logging.getLogger(__name__)


class AuditAction(str, enum.Enum):
    """Audited action vocabulary."""

    DOCUMENT_CREATE = "document.create"
    DOCUMENT_DELETE = "document.delete"
    DOCUMENT_INDEX = "document.index"
    QA_QUERY = "qa.query"


def _scope(context):
    if context is None:
        return None, None, None, None
    return (
        getattr(context.user, "id", None),
        getattr(context.tenant, "id", None),
        getattr(context.workspace, "id", None),
        getattr(context.knowledge_base, "id", None),
    )


class AuditService:
    """Writes audit rows. Success rows share the caller's transaction;
    failure rows are committed in an independent session."""

    def record(
        self,
        db: Session,
        *,
        action: "AuditAction",
        resource_type: str,
        resource_id: str | None,
        result: AuditResult,
        context=None,
        detail: str | None = None,
    ) -> AuditLog:
        """Add an audit row to the caller's session (caller commits)."""
        actor_id, tenant_id, workspace_id, kb_id = _scope(context)
        row = AuditLog(
            actor_user_id=actor_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            knowledge_base_id=kb_id,
            action=action.value,
            resource_type=resource_type,
            resource_id=resource_id,
            result=result,
            detail=detail,
            request_id=get_request_id(),
            client_ip=get_client_ip(),
        )
        db.add(row)
        db.flush()
        return row

    def record_failure(
        self,
        *,
        action: "AuditAction",
        resource_type: str,
        resource_id: str | None,
        context=None,
        detail: str | None = None,
    ) -> None:
        """Write a FAILURE row in an independent session; never raises."""
        try:
            db = SessionLocal()
            try:
                self.record(
                    db,
                    action=action,
                    resource_type=resource_type,
                    resource_id=resource_id,
                    result=AuditResult.FAILURE,
                    context=context,
                    detail=detail,
                )
                db.commit()
            finally:
                db.close()
        except Exception:  # noqa: BLE001 - auditing must never break a request
            logger.exception("Failed to write failure audit log")
