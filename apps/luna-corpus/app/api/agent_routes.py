"""Agent API 路由：完整生产管线（配额准入 + 治理 + 轨迹 + 审计 + 会话记忆 + 成本计量）。"""  # noqa: E501
import json
import logging
import time
import uuid
from collections.abc import AsyncGenerator
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.agent.core.context import AgentRunContext
from app.agent.core.governance import HaltSignal
from app.agent.core.trace import TraceRecorder
from app.agent.factory import AgentFactory
from app.agent.registry import ToolRegistry
from app.agent.tool import Tool
from app.agent.tools import calculator_tool, create_rag_search_tool, current_time_tool
from app.api.auth import AuthenticatedRequestContext, require_permission
from app.auth.permissions import PermissionSlug
from app.core.config import AgentMode, get_settings
from app.cost.enforcement import QuotaExceeded, check_quota
from app.cost.recorder import record_usage
from app.db.database import get_db
from app.db.models import AgentRunStatus, AuditResult, Conversation, MessageRole
from app.observability.metrics import QUOTA_REJECTED_TOTAL
from app.security.audit import AuditAction, AuditService
from app.services.llm import TokenUsage
from app.services.memory import (
    add_message_to_conversation,
    format_conversation_history,
    get_conversation_messages,
    get_memory_context,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/agent", tags=["agent"])

# P0 遗留：模块级 ad-hoc 工具注册（POST /tools），仅为兼容旧客户端。
# 新版管线不建议再依赖它——工具将由知识库配置驱动。
_registered_tools: dict[str, Tool] = {}


# ================================
# Request / Response Models
# ================================


class AgentQueryRequest(BaseModel):
    """Agent 查询请求。"""

    query: str = Field(..., min_length=1, max_length=2000)
    mode: str = Field(
        default="direct", description="Agent 模式：direct/react/plan/langgraph"
    )
    available_tools: list[str] | None = Field(
        default=None, description="仅暴露给 agent 的工具白名单；缺省=使用默认工具"
    )
    stream: bool = Field(default=False, description="是否走流式（保留字段）")
    conversation_id: str | None = Field(
        default=None, description="可选会话 ID，用于载入历史与写回消息"
    )


class ToolCallInfo(BaseModel):
    """工具调用摘要（新版管线不再实时透出，保留字段用于兼容）。"""

    tool: str
    args: dict[str, Any]
    result: str | None = None
    success: bool = True


class AgentQueryResponse(BaseModel):
    """Agent 查询响应。"""

    answer: str
    run_id: str = ""
    tool_calls: list[ToolCallInfo] = []
    mode: str
    steps: int = 0
    latency_ms: int = 0


class ToolInfo(BaseModel):
    """工具描述。"""

    name: str
    description: str
    parameters_schema: dict[str, Any]


class ToolListResponse(BaseModel):
    """工具列表响应。"""

    tools: list[ToolInfo]


class ToolRegisterRequest(BaseModel):
    """工具注册请求（deprecated）。"""

    name: str = Field(..., min_length=1)
    description: str = Field(..., min_length=1)
    parameters_schema: dict[str, Any]


# ================================
# 工具注册表辅助
# ================================


def get_default_registry(knowledge_base_id: str) -> ToolRegistry:
    """按知识库构造默认工具注册表（含内建工具 + 模块级 ad-hoc 注册）。"""
    registry = ToolRegistry()
    registry.register(create_rag_search_tool(knowledge_base_id))
    registry.register(calculator_tool)
    registry.register(current_time_tool)
    for tool in _registered_tools.values():
        registry.register(tool)
    return registry


def filter_registry(
    registry: ToolRegistry, available_tools: list[str] | None
) -> ToolRegistry:
    """按名称白名单过滤工具注册表；None=不过滤，空列表=空注册表。"""
    if available_tools is None:
        return registry

    filtered_registry = ToolRegistry()
    for tool_name in available_tools:
        tool = registry.get(tool_name)
        if tool:
            filtered_registry.register(tool)
    return filtered_registry


# ================================
# 管线辅助
# ================================


def _parse_mode(mode_str: str) -> AgentMode:
    """解析 mode 字符串；失败抛 400。"""
    try:
        return AgentMode(mode_str.lower())
    except ValueError as exc:
        raise HTTPException(
            status_code=400, detail=f"Invalid mode: {mode_str}"
        ) from exc


def _conversation_belongs_to_kb(
    db: Session, conversation_id: str, knowledge_base_id: str
) -> bool:
    """校验 conversation 是否属于当前知识库。

    P0 阶段 Conversation 的租户/工作区归属通过 knowledge_base FK 隐式绑定
    （KnowledgeBase → Workspace → Tenant），因此 KB 归属校验足以防跨租户串扰。
    """
    return (
        db.query(Conversation.id)
        .filter(
            Conversation.id == conversation_id,
            Conversation.knowledge_base_id == knowledge_base_id,
        )
        .first()
        is not None
    )


def _load_memory_history(
    db: Session,
    conversation_id: str | None,
    knowledge_base_id: str | None = None,
) -> str:
    """载入会话历史（含 summary + 最近消息）；无会话 ID 或跨 KB 越权则返回空串。

    关键：拿到 conversation_id 后必须先按 knowledge_base_id 校验归属，
    否则攻击者传入其它 KB 的 conversation_id 即可窃取或注入他人历史。
    """
    if not conversation_id:
        return ""
    if knowledge_base_id and not _conversation_belongs_to_kb(
        db, conversation_id, knowledge_base_id
    ):
        logger.warning(
            "agent.memory.cross_kb_conversation_denied",
            extra={
                "conversation_id": conversation_id,
                "knowledge_base_id": knowledge_base_id,
            },
        )
        return ""
    mem, _ = get_memory_context(db, conversation_id)
    history = format_conversation_history(
        get_conversation_messages(db, conversation_id)
    )
    return f"{mem}\n{history}".strip()


def _build_run_context(
    request: AgentQueryRequest,
    ctx_auth: AuthenticatedRequestContext,
    db: Session,
) -> AgentRunContext:
    """构建 AgentRunContext，含全局治理参数、query 与 memory_history。"""
    settings = get_settings()
    return AgentRunContext(
        run_id=str(uuid.uuid4()),
        tenant_id=ctx_auth.tenant.id,
        workspace_id=ctx_auth.workspace.id,
        knowledge_base_id=ctx_auth.knowledge_base.id,
        user_id=ctx_auth.user.id,
        conversation_id=request.conversation_id,
        mode=request.mode,
        max_steps=settings.agent_max_steps,
        timeout_s=settings.agent_timeout_s,
        max_recursion_depth=settings.agent_max_recursion_depth,
        start_time=time.time(),
        query=request.query,
        memory_history=_load_memory_history(
            db, request.conversation_id, ctx_auth.knowledge_base.id
        ),
    )


def _record_agent_usage(
    db: Session,
    *,
    ctx_auth: AuthenticatedRequestContext,
    run_ctx: AgentRunContext,
) -> None:
    """把 run 级累加 token 折算入 usage_records（record_usage 内部 fail-safe）。"""
    if not (run_ctx.total_input_tokens or run_ctx.total_output_tokens):
        return
    settings = get_settings()
    record_usage(
        db,
        tenant_id=ctx_auth.tenant.id,
        workspace_id=ctx_auth.workspace.id,
        knowledge_base_id=ctx_auth.knowledge_base.id,
        interaction_id=run_ctx.run_id,
        usage=TokenUsage(
            input_tokens=run_ctx.total_input_tokens,
            output_tokens=run_ctx.total_output_tokens,
            model=settings.ark_model,
            provider=settings.llm_provider.value,
        ),
    )


def _persist_conversation_messages(
    db: Session,
    *,
    conversation_id: str | None,
    knowledge_base_id: str | None,
    query: str,
    answer: str,
) -> None:
    """会话开启时把本轮 user/assistant 消息落库；跨 KB 越权时静默丢弃。"""
    if not conversation_id or not answer:
        return
    if knowledge_base_id and not _conversation_belongs_to_kb(
        db, conversation_id, knowledge_base_id
    ):
        logger.warning(
            "agent.memory.cross_kb_persist_denied",
            extra={
                "conversation_id": conversation_id,
                "knowledge_base_id": knowledge_base_id,
            },
        )
        return
    add_message_to_conversation(db, conversation_id, MessageRole.USER, query)
    add_message_to_conversation(db, conversation_id, MessageRole.ASSISTANT, answer)


def _check_quota_or_429(db: Session, tenant_id: str, workspace_id: str) -> None:
    """事前配额准入：超限抛 429；系统故障时 check_quota 内部已 fail-open。"""
    try:
        check_quota(db, tenant_id, workspace_id)
    except QuotaExceeded as exc:
        QUOTA_REJECTED_TOTAL.labels(scope_type=exc.scope_type).inc()
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=str(exc),
        ) from exc


async def _run_pipeline(
    request: AgentQueryRequest,
    ctx_auth: AuthenticatedRequestContext,
    db: Session,
) -> tuple[AgentRunContext, Any, int]:
    """执行完整 agent 管线，返回 (run_ctx, LoopResult, latency_ms)。

    调用方需在异常处理外确保管线的 trace/audit/记忆/成本记录已闭合；
    本函数负责在正常/HaltSignal/未知异常三条路径上都把 trace.end_run 写入。
    """
    settings = get_settings()

    mode = _parse_mode(request.mode)
    run_ctx = _build_run_context(request, ctx_auth, db)
    trace = TraceRecorder(db)
    trace.start_run(run_ctx, request.query)

    try:
        registry = filter_registry(
            get_default_registry(ctx_auth.knowledge_base.id),
            request.available_tools,
        )
        agent = AgentFactory.create(
            mode=mode,
            tools=registry,
            max_steps=settings.agent_max_steps,
            timeout_s=settings.agent_timeout_s,
            max_recursion_depth=settings.agent_max_recursion_depth,
        )
        result = await agent.run(run_ctx, trace, db)
        latency_ms = int(run_ctx.elapsed_s() * 1000)

        trace.end_run(
            run_ctx,
            status=result.status,
            final_answer=result.answer,
            total_cost=0,
            latency_ms=latency_ms,
        )

        AuditService().record(
            db,
            action=AuditAction.AGENT_QUERY,
            resource_type="agent_run",
            resource_id=run_ctx.run_id,
            result=AuditResult.SUCCESS,
            context=ctx_auth,
            detail=json.dumps(
                {
                    "knowledge_base_id": run_ctx.knowledge_base_id,
                    "mode": run_ctx.mode,
                },
                ensure_ascii=False,
            ),
        )

        _persist_conversation_messages(
            db,
            conversation_id=request.conversation_id,
            knowledge_base_id=ctx_auth.knowledge_base.id,
            query=request.query,
            answer=result.answer,
        )

        _record_agent_usage(db, ctx_auth=ctx_auth, run_ctx=run_ctx)

        db.commit()
        return run_ctx, result, latency_ms

    except HaltSignal as halt:
        latency_ms = int(run_ctx.elapsed_s() * 1000)
        trace.end_run(
            run_ctx,
            status=halt.status,
            final_answer="",
            total_cost=0,
            latency_ms=latency_ms,
            error_message=halt.reason,
        )
        try:
            db.commit()
        except Exception:  # noqa: BLE001 - 审计/轨迹尽力而为
            # 刻意保留 try/except/pass：rollback 本身失败也必须吞掉，
            # 避免掩盖上层 HaltSignal。
            try:  # noqa: SIM105
                db.rollback()
            except Exception:
                pass
        # HaltSignal → HTTP：按治理熔断种类精细分派，前端可据此差异化提示与重试策略。
        if halt.status == AgentRunStatus.HALTED_TIMEOUT:
            http_status = status.HTTP_504_GATEWAY_TIMEOUT
        elif halt.status == AgentRunStatus.HALTED_QUOTA:
            http_status = status.HTTP_429_TOO_MANY_REQUESTS
        else:
            # HALTED_MAX_STEPS（含 recursion_depth 越界）：
            # 仍语义为"给的空间不够，减少复杂度重试"，返 429。
            http_status = status.HTTP_429_TOO_MANY_REQUESTS
        raise HTTPException(
            status_code=http_status,
            detail=halt.reason,
        ) from halt

    except HTTPException:
        # 上游已构造好状态码（例如 _parse_mode），直接透出
        raise

    except Exception as exc:
        latency_ms = int(run_ctx.elapsed_s() * 1000)
        trace.end_run(
            run_ctx,
            status=AgentRunStatus.FAILED,
            final_answer="",
            total_cost=0,
            latency_ms=latency_ms,
            error_message=str(exc),
        )
        try:
            db.commit()
        except Exception:  # noqa: BLE001
            # 刻意保留 try/except/pass：rollback 本身失败也必须吞掉，保证原异常能上抛。
            try:  # noqa: SIM105
                db.rollback()
            except Exception:
                pass
        raise


# ================================
# 路由：/query
# ================================


@router.post("/query", response_model=AgentQueryResponse)
async def query(
    request: AgentQueryRequest,
    db: Annotated[Session, Depends(get_db)],
    context: Annotated[
        AuthenticatedRequestContext,
        Depends(require_permission(PermissionSlug.QA_QUERY)),
    ],
) -> AgentQueryResponse:
    """执行一次 agent 查询（完整生产管线）。

    管线顺序：
      1. 事前配额准入（超限 → 429）
      2. 构建 AgentRunContext + 载入会话记忆
      3. TraceRecorder.start_run 写入 agent_runs（RUNNING）
      4. AgentFactory.create + agent.run(ctx, trace, db) 执行
      5. trace.end_run 写入终态
      6. AuditService.record(AGENT_QUERY, SUCCESS)
      7. 若有 conversation_id，会话消息落库
      8. record_usage 记录成本明细并累加日度计数器
      9. 返回响应（含 run_id）；工具调用明细见 GET /api/v1/agent/runs/{run_id}
    """
    # 先做纯字符串校验，避免为无效 mode 也起一次 trace/run
    _parse_mode(request.mode)
    _check_quota_or_429(db, context.tenant.id, context.workspace.id)

    run_ctx, result, latency_ms = await _run_pipeline(request, context, db)

    return AgentQueryResponse(
        answer=result.answer,
        run_id=run_ctx.run_id,
        mode=request.mode,
        steps=result.steps,
        latency_ms=latency_ms,
        tool_calls=[],
    )


# ================================
# 路由：/stream
# ================================


async def _agent_sse_generator(
    request: AgentQueryRequest,
    context: AuthenticatedRequestContext,
    db: Session,
) -> AsyncGenerator[str, None]:
    """SSE 生成器：P0 阶段仅落地 run_start + done 两事件。

    完整轨迹（含每步 reasoning/tool_call）走库落 agent_steps，
    前端经 GET /api/v1/agent/runs/{run_id} 拉取；逐步事件推流放到 P1 follow-up。
    """
    try:
        run_ctx, result, latency_ms = await _run_pipeline(request, context, db)
        yield "data: " + json.dumps(
            {
                "event": "run_start",
                "data": {"run_id": run_ctx.run_id, "mode": request.mode},
            }
        ) + "\n\n"
        yield "data: " + json.dumps(
            {
                "event": "done",
                "data": {
                    "run_id": run_ctx.run_id,
                    "answer": result.answer,
                    "status": result.status.value,
                    "steps": result.steps,
                    "latency_ms": latency_ms,
                },
            }
        ) + "\n\n"
    except HTTPException as http_exc:
        # 429/400 等仍以 SSE 错误事件形式向下游透出，避免连接层直接断开
        yield "data: " + json.dumps(
            {
                "event": "error",
                "data": {
                    "status_code": http_exc.status_code,
                    "detail": http_exc.detail,
                },
            }
        ) + "\n\n"
    except Exception as exc:  # noqa: BLE001
        yield "data: " + json.dumps(
            {"event": "error", "data": {"detail": str(exc)}}
        ) + "\n\n"


@router.post("/stream")
async def stream_query(
    request: AgentQueryRequest,
    db: Annotated[Session, Depends(get_db)],
    context: Annotated[
        AuthenticatedRequestContext,
        Depends(require_permission(PermissionSlug.QA_QUERY)),
    ],
):
    """流式执行 agent 查询（SSE）。事前配额准入与 /query 一致。"""
    _parse_mode(request.mode)
    _check_quota_or_429(db, context.tenant.id, context.workspace.id)

    return StreamingResponse(
        _agent_sse_generator(request, context, db),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ================================
# 路由：/tools 与 /modes
# ================================


@router.get("/tools", response_model=ToolListResponse)
async def list_tools(
    context: Annotated[
        AuthenticatedRequestContext,
        Depends(require_permission(PermissionSlug.KNOWLEDGE_BASE_READ)),
    ],
) -> ToolListResponse:
    """列出当前知识库可用工具。"""
    registry = get_default_registry(context.knowledge_base.id)
    tools = [
        ToolInfo(
            name=tool.name,
            description=tool.description,
            parameters_schema=tool.parameters_schema,
        )
        for tool in registry.list_all()
    ]
    return ToolListResponse(tools=tools)


@router.post("/tools")
async def register_tool(
    request: ToolRegisterRequest,
    context: Annotated[
        AuthenticatedRequestContext,
        Depends(require_permission(PermissionSlug.KNOWLEDGE_BASE_MANAGE)),
    ],
):
    """[DEPRECATED] 注册一个进程级工具。

    P0 阶段保留此端点以兼容旧客户端，但强烈建议改用知识库配置驱动的工具装配。
    该注册只在当前进程内存中生效，不做持久化，也不做工作区隔离。
    """
    tool = Tool(
        name=request.name,
        description=request.description,
        parameters_schema=request.parameters_schema,
    )
    _registered_tools[request.name] = tool
    return {"message": f"Tool '{request.name}' registered", "name": request.name}


@router.get("/modes")
async def list_modes(
    context: Annotated[
        AuthenticatedRequestContext,
        Depends(require_permission(PermissionSlug.KNOWLEDGE_BASE_READ)),
    ],
):
    """列出可用的 agent 执行模式。"""
    return {
        "modes": [
            {"mode": "direct", "description": "Direct execution - single LLM call"},
            {"mode": "react", "description": "ReAct loop - reasoning and acting"},
            {
                "mode": "plan",
                "description": "Plan-then-Execute - plan first, execute second",
            },
            {
                "mode": "langgraph",
                "description": (
                    "P0: alias of react (single loop); "
                    "state graph deferred to P1"
                ),
            },
        ]
    }
