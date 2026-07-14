"""Authenticated request context and RBAC dependencies."""
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.api.context import RequestContext, get_request_context
from app.auth.tokens import TokenError, decode_access_token
from app.db.database import get_db
from app.db.models import Permission, User, WorkspaceMembership
from app.security.context import set_identity_context


@dataclass(frozen=True)
class AuthenticatedRequestContext(RequestContext):
    user: User
    membership: WorkspaceMembership
    permissions: frozenset[str]


def get_authenticated_context(
    db: Session,
    token: str | None,
    x_tenant_id: str | None,
    x_workspace_id: str | None,
    x_knowledge_base_id: str | None,
    required_permissions: Sequence[str],
) -> AuthenticatedRequestContext:
    resource_context = get_request_context(
        db=db,
        x_tenant_id=x_tenant_id,
        x_workspace_id=x_workspace_id,
        x_knowledge_base_id=x_knowledge_base_id,
    )

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token",
        )
    try:
        user_id = decode_access_token(token)
    except TokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User is inactive",
        )

    membership = (
        db.query(WorkspaceMembership)
        .filter(
            WorkspaceMembership.user_id == user.id,
            WorkspaceMembership.workspace_id == resource_context.workspace.id,
        )
        .first()
    )
    if not membership:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Workspace membership required",
        )
    if not membership.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Workspace membership is inactive",
        )

    effective_permissions = frozenset(
        permission.slug
        for role in membership.roles
        for permission in role.permissions
    )
    missing_permissions = [
        permission for permission in required_permissions if permission not in effective_permissions
    ]
    if missing_permissions:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Missing required permission: {missing_permissions[0]}",
        )

    set_identity_context(user.id, resource_context.tenant.id)

    return AuthenticatedRequestContext(
        tenant=resource_context.tenant,
        workspace=resource_context.workspace,
        knowledge_base=resource_context.knowledge_base,
        user=user,
        membership=membership,
        permissions=effective_permissions,
    )


def require_permission(
    *required_permissions: str,
) -> Callable[..., AuthenticatedRequestContext]:
    def dependency(
        db: Annotated[Session, Depends(get_db)],
        authorization: Annotated[str | None, Header()] = None,
        x_tenant_id: Annotated[str | None, Header(alias="X-Tenant-Id")] = None,
        x_workspace_id: Annotated[str | None, Header(alias="X-Workspace-Id")] = None,
        x_knowledge_base_id: Annotated[
            str | None,
            Header(alias="X-Knowledge-Base-Id"),
        ] = None,
    ) -> AuthenticatedRequestContext:
        return get_authenticated_context(
            db=db,
            token=(
                authorization.removeprefix("Bearer ")
                if authorization and authorization.startswith("Bearer ")
                else None
            ),
            x_tenant_id=x_tenant_id,
            x_workspace_id=x_workspace_id,
            x_knowledge_base_id=x_knowledge_base_id,
            required_permissions=required_permissions,
        )

    return dependency
