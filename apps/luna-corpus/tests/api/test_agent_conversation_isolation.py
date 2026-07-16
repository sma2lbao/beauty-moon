"""跨知识库会话隔离：agent /query 与 /stream 必须校验 conversation 归属。"""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.agent.core.llm_loop import LoopResult
from app.auth.permissions import PermissionSlug
from app.auth.tokens import create_access_token
from app.db.database import get_db
from app.db.models import (
    AgentRunStatus,
    Base,
    Conversation,
    KnowledgeBase,
    Message,
    MessageRole,
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
    kb_a = KnowledgeBase(name="A", slug="a", workspace=workspace)
    kb_b = KnowledgeBase(name="B", slug="b", workspace=workspace)
    session.add_all([kb_a, kb_b])
    session.commit()

    # 一个属于 kb_b 的会话，已经有一条 assistant 消息作为"敏感历史"
    conv_b = Conversation(title="Secret", knowledge_base_id=kb_b.id)
    session.add(conv_b)
    session.commit()
    session.add(
        Message(
            conversation_id=conv_b.id,
            role=MessageRole.ASSISTANT,
            content="SECRET_FROM_KB_B",
            token_count=5,
        )
    )
    session.commit()

    context = {
        "tenant_id": tenant.id,
        "workspace_id": workspace.id,
        "kb_a_id": kb_a.id,
        "kb_b_id": kb_b.id,
        "conv_b_id": conv_b.id,
    }
    session.close()

    yield engine, Session, context
    engine.dispose()


@pytest.fixture
def client(app_db):
    _, Session, _ = app_db

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


def _grant(Session, workspace_id, label, slugs):
    session = Session()
    try:
        user = User(email=f"{label}@example.com", display_name=label)
        perms = []
        for slug in slugs:
            perm = session.query(Permission).filter(Permission.slug == slug).first()
            if not perm:
                perm = Permission(name=slug, slug=slug, description=slug)
            perms.append(perm)
        role = Role(name=label, slug=label, is_system=True, permissions=perms)
        member = WorkspaceMembership(user=user, workspace_id=workspace_id, roles=[role])
        session.add(member)
        session.commit()
        return user.id
    finally:
        session.close()


def _headers(context, kb_id, user_id):
    return {
        "Authorization": f"Bearer {create_access_token(user_id)}",
        "X-Tenant-Id": context["tenant_id"],
        "X-Workspace-Id": context["workspace_id"],
        "X-Knowledge-Base-Id": kb_id,
    }


def test_cross_kb_conversation_id_does_not_leak_history(client, app_db):
    """从 KB-A 上下文提交 KB-B 的 conversation_id：
    - 历史不应被载入（memory_history 为空串）；
    - 不应把本轮消息写入 KB-B 的 conversation。
    """
    _, Session, context = app_db
    user_id = _grant(
        Session,
        context["workspace_id"],
        "agent_cross_kb",
        [PermissionSlug.QA_QUERY],
    )

    with patch("app.api.agent_routes.AgentFactory.create") as mock_create:
        mock_agent = AsyncMock()
        mock_agent.run.return_value = LoopResult(
            answer="ok",
            status=AgentRunStatus.COMPLETED,
            steps=1,
        )
        mock_create.return_value = mock_agent

        response = client.post(
            "/api/v1/agent/query",
            headers=_headers(context, context["kb_a_id"], user_id),
            json={
                "query": "任何问题",
                "mode": "direct",
                "conversation_id": context["conv_b_id"],  # 跨 KB 越权尝试
            },
        )

    assert response.status_code == 200

    # 校验点 1：agent.run 收到的 ctx.memory_history 不能包含 KB-B 的 SECRET
    ctx_arg = mock_agent.run.call_args.args[0]
    assert "SECRET_FROM_KB_B" not in (ctx_arg.memory_history or "")
    assert (ctx_arg.memory_history or "") == ""

    # 校验点 2：KB-B 的 conversation 消息数不应因为本次跨 KB 请求增加
    session = Session()
    try:
        remaining = (
            session.query(Message)
            .filter(Message.conversation_id == context["conv_b_id"])
            .all()
        )
    finally:
        session.close()
    # 原本 1 条 SECRET；本次请求不应新增 user/assistant 两条
    assert len(remaining) == 1
    assert remaining[0].content == "SECRET_FROM_KB_B"
