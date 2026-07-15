"""Tenant, workspace, and knowledge-base API routes."""
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.api.auth import AuthenticatedRequestContext, require_permission
from app.auth.permissions import PermissionSlug
from app.auth.tokens import TokenError, decode_access_token
from app.db.database import get_db
from app.db.models import (
    KnowledgeBase,
    Permission,
    Role,
    Tenant,
    User,
    Workspace,
    WorkspaceMembership,
    role_permissions,
    workspace_membership_roles,
)

router = APIRouter(prefix="/api/v1", tags=["tenants"])


def _authenticate_user(db: Session, authorization: str | None) -> User:
    """Resolve the caller from a bearer token, raising 401/403 on failure."""
    token = (
        authorization.removeprefix("Bearer ")
        if authorization and authorization.startswith("Bearer ")
        else None
    )
    if not token:
        raise HTTPException(status_code=401, detail="Missing bearer token")
    try:
        user_id = decode_access_token(token)
    except TokenError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="User is inactive")
    return user


class TenantCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    slug: str = Field(..., min_length=1, max_length=255)


class TenantResponse(BaseModel):
    id: str
    name: str
    slug: str

    model_config = ConfigDict(from_attributes=True)


class TenantListResponse(BaseModel):
    tenants: list[TenantResponse]
    total: int


class WorkspaceCreate(BaseModel):
    tenant_id: str
    name: str = Field(..., min_length=1, max_length=255)
    slug: str = Field(..., min_length=1, max_length=255)


class WorkspaceResponse(BaseModel):
    id: str
    tenant_id: str
    name: str
    slug: str

    model_config = ConfigDict(from_attributes=True)


class WorkspaceListResponse(BaseModel):
    workspaces: list[WorkspaceResponse]
    total: int


class KnowledgeBaseCreate(BaseModel):
    workspace_id: str
    name: str = Field(..., min_length=1, max_length=255)
    slug: str = Field(..., min_length=1, max_length=255)
    description: str | None = None


class KnowledgeBaseResponse(BaseModel):
    id: str
    workspace_id: str
    name: str
    slug: str
    description: str | None

    model_config = ConfigDict(from_attributes=True)


class KnowledgeBaseListResponse(BaseModel):
    knowledge_bases: list[KnowledgeBaseResponse]
    total: int


@router.post("/tenants", response_model=TenantResponse, status_code=status.HTTP_201_CREATED)
def create_tenant(
    tenant: TenantCreate,
    db: Annotated[Session, Depends(get_db)],
    authorization: Annotated[str | None, Header()] = None,
) -> TenantResponse:
    _authenticate_user(db, authorization)
    db_tenant = Tenant(name=tenant.name, slug=tenant.slug)
    db.add(db_tenant)
    db.commit()
    db.refresh(db_tenant)
    return TenantResponse.model_validate(db_tenant)


@router.get("/tenants", response_model=TenantListResponse)
def list_tenants(
    db: Annotated[Session, Depends(get_db)],
    authorization: Annotated[str | None, Header()] = None,
) -> TenantListResponse:
    user = _authenticate_user(db, authorization)

    tenants = (
        db.query(Tenant)
        .join(Workspace)
        .join(WorkspaceMembership)
        .filter(
            WorkspaceMembership.user_id == user.id,
            WorkspaceMembership.is_active == True,
        )
        .distinct()
        .order_by(Tenant.created_at.desc())
        .all()
    )
    return TenantListResponse(tenants=tenants, total=len(tenants))


@router.post(
    "/workspaces",
    response_model=WorkspaceResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_workspace(
    workspace: WorkspaceCreate,
    db: Annotated[Session, Depends(get_db)],
    authorization: Annotated[str | None, Header()] = None,
) -> WorkspaceResponse:
    user = _authenticate_user(db, authorization)

    tenant = db.query(Tenant).filter(Tenant.id == workspace.tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    has_manage = (
        db.query(WorkspaceMembership.id)
        .join(Workspace, Workspace.id == WorkspaceMembership.workspace_id)
        .join(
            workspace_membership_roles,
            workspace_membership_roles.c.membership_id == WorkspaceMembership.id,
        )
        .join(Role, Role.id == workspace_membership_roles.c.role_id)
        .join(role_permissions, role_permissions.c.role_id == Role.id)
        .join(Permission, Permission.id == role_permissions.c.permission_id)
        .filter(
            WorkspaceMembership.user_id == user.id,
            WorkspaceMembership.is_active == True,  # noqa: E712
            Workspace.tenant_id == workspace.tenant_id,
            Permission.slug == PermissionSlug.WORKSPACE_MANAGE,
        )
        .first()
        is not None
    )
    if not has_manage:
        raise HTTPException(
            status_code=403,
            detail=f"Missing required permission: {PermissionSlug.WORKSPACE_MANAGE}",
        )

    db_workspace = Workspace(
        tenant_id=workspace.tenant_id,
        name=workspace.name,
        slug=workspace.slug,
    )
    db.add(db_workspace)
    db.commit()
    db.refresh(db_workspace)
    return WorkspaceResponse.model_validate(db_workspace)


@router.get("/workspaces", response_model=WorkspaceListResponse)
def list_workspaces(
    db: Annotated[Session, Depends(get_db)],
    tenant_id: str | None = Query(default=None),
    authorization: Annotated[str | None, Header()] = None,
) -> WorkspaceListResponse:
    user = _authenticate_user(db, authorization)

    query = (
        db.query(Workspace)
        .join(WorkspaceMembership)
        .filter(
            WorkspaceMembership.user_id == user.id,
            WorkspaceMembership.is_active == True,
        )
    )
    if tenant_id:
        query = query.filter(Workspace.tenant_id == tenant_id)
    workspaces = query.order_by(Workspace.created_at.desc()).all()
    return WorkspaceListResponse(workspaces=workspaces, total=len(workspaces))


@router.post(
    "/knowledge-bases",
    response_model=KnowledgeBaseResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_knowledge_base(
    knowledge_base: KnowledgeBaseCreate,
    db: Annotated[Session, Depends(get_db)],
    context: Annotated[
        AuthenticatedRequestContext,
        Depends(require_permission(PermissionSlug.KNOWLEDGE_BASE_MANAGE)),
    ],
) -> KnowledgeBaseResponse:
    workspace = (
        db.query(Workspace)
        .filter(Workspace.id == knowledge_base.workspace_id)
        .first()
    )
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")

    if workspace.id != context.workspace.id:
        raise HTTPException(status_code=404, detail="Workspace not found")

    db_knowledge_base = KnowledgeBase(
        workspace_id=knowledge_base.workspace_id,
        name=knowledge_base.name,
        slug=knowledge_base.slug,
        description=knowledge_base.description,
    )
    db.add(db_knowledge_base)
    db.commit()
    db.refresh(db_knowledge_base)
    return KnowledgeBaseResponse.model_validate(db_knowledge_base)


@router.get("/knowledge-bases", response_model=KnowledgeBaseListResponse)
def list_knowledge_bases(
    db: Annotated[Session, Depends(get_db)],
    context: Annotated[
        AuthenticatedRequestContext,
        Depends(require_permission(PermissionSlug.KNOWLEDGE_BASE_READ)),
    ],
    workspace_id: str | None = Query(default=None),
) -> KnowledgeBaseListResponse:
    query = db.query(KnowledgeBase).filter(KnowledgeBase.workspace_id == context.workspace.id)
    if workspace_id and workspace_id != context.workspace.id:
        raise HTTPException(status_code=404, detail="Workspace not found")
    knowledge_bases = query.order_by(KnowledgeBase.created_at.desc()).all()
    return KnowledgeBaseListResponse(
        knowledge_bases=knowledge_bases,
        total=len(knowledge_bases),
    )
