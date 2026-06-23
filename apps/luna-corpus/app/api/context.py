"""Request context dependencies for knowledge-base scoped APIs."""
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import KnowledgeBase, Tenant, Workspace


@dataclass(frozen=True)
class RequestContext:
    tenant: Tenant
    workspace: Workspace
    knowledge_base: KnowledgeBase


def get_request_context(
    db: Session,
    x_tenant_id: str | None,
    x_workspace_id: str | None,
    x_knowledge_base_id: str | None,
) -> RequestContext:
    missing_headers = []
    if not x_tenant_id:
        missing_headers.append("X-Tenant-Id")
    if not x_workspace_id:
        missing_headers.append("X-Workspace-Id")
    if not x_knowledge_base_id:
        missing_headers.append("X-Knowledge-Base-Id")

    if missing_headers:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Missing required header: {', '.join(missing_headers)}",
        )

    tenant = db.query(Tenant).filter(Tenant.id == x_tenant_id).first()
    workspace = db.query(Workspace).filter(Workspace.id == x_workspace_id).first()
    knowledge_base = (
        db.query(KnowledgeBase)
        .filter(KnowledgeBase.id == x_knowledge_base_id)
        .first()
    )

    if not tenant or not workspace or not knowledge_base:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Knowledge base context not found",
        )

    if workspace.tenant_id != tenant.id or knowledge_base.workspace_id != workspace.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Knowledge base context not found",
        )

    return RequestContext(
        tenant=tenant,
        workspace=workspace,
        knowledge_base=knowledge_base,
    )


def require_request_context(
    db: Annotated[Session, Depends(get_db)],
    x_tenant_id: Annotated[str | None, Header(alias="X-Tenant-Id")] = None,
    x_workspace_id: Annotated[str | None, Header(alias="X-Workspace-Id")] = None,
    x_knowledge_base_id: Annotated[
        str | None,
        Header(alias="X-Knowledge-Base-Id"),
    ] = None,
) -> RequestContext:
    return get_request_context(
        db=db,
        x_tenant_id=x_tenant_id,
        x_workspace_id=x_workspace_id,
        x_knowledge_base_id=x_knowledge_base_id,
    )
