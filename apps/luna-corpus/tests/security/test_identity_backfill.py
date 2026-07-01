"""get_authenticated_context backfills identity contextvars."""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.auth import get_authenticated_context
from app.db.database import Base
from app.db.models import (
    KnowledgeBase,
    Permission,
    Role,
    Tenant,
    User,
    Workspace,
    WorkspaceMembership,
)
from app.security.context import get_tenant_id, get_user_id, reset_request_context


def test_authenticated_context_sets_identity():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine)()
    reset_request_context()

    tenant = Tenant(name="Acme", slug="acme")
    workspace = Workspace(name="R", slug="r", tenant=tenant)
    kb = KnowledgeBase(name="Docs", slug="docs", workspace=workspace)
    perm = Permission(name="qa:query", slug="qa:query", description="q")
    role = Role(name="reader", slug="reader", is_system=True, permissions=[perm])
    user = User(email="u@example.com", display_name="U")
    membership = WorkspaceMembership(user=user, workspace=workspace, roles=[role])
    db.add_all([kb, membership])
    db.commit()

    get_authenticated_context(
        db=db,
        x_user_id=user.id,
        x_tenant_id=tenant.id,
        x_workspace_id=workspace.id,
        x_knowledge_base_id=kb.id,
        required_permissions=["qa:query"],
    )

    assert get_user_id() == user.id
    assert get_tenant_id() == tenant.id
