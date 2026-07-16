"""Agent 执行回放 API：list runs 与 run 详情（含有序 steps）。"""
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.auth import AuthenticatedRequestContext, require_permission
from app.auth.permissions import PermissionSlug
from app.db.database import get_db
from app.db.models import AgentRun, AgentStep

router = APIRouter(prefix="/api/v1/agent/runs", tags=["agent"])


@router.get("")
async def list_runs(
    db: Annotated[Session, Depends(get_db)],
    context: Annotated[
        AuthenticatedRequestContext,
        Depends(require_permission(PermissionSlug.KNOWLEDGE_BASE_READ)),
    ],
    conversation_id: str | None = Query(None),
    user_id: str | None = Query(None),
    status: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
) -> dict:
    """列出当前知识库下的 agent 执行记录（按 created_at 倒序）。

    仅返回 knowledge_base_id == 当前上下文的记录，杜绝跨库泄漏。
    """
    q = db.query(AgentRun).filter(
        AgentRun.knowledge_base_id == context.knowledge_base.id
    )
    if conversation_id:
        q = q.filter(AgentRun.conversation_id == conversation_id)
    if user_id:
        q = q.filter(AgentRun.user_id == user_id)
    if status:
        q = q.filter(AgentRun.status == status)
    rows = q.order_by(AgentRun.created_at.desc()).limit(limit).all()
    return {
        "runs": [
            {
                "id": r.id,
                "query": r.query,
                "mode": r.mode,
                "status": r.status.value,
                "steps_count": r.steps_count,
                "latency_ms": r.latency_ms,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]
    }


@router.get("/{run_id}")
async def get_run(
    run_id: str,
    db: Annotated[Session, Depends(get_db)],
    context: Annotated[
        AuthenticatedRequestContext,
        Depends(require_permission(PermissionSlug.KNOWLEDGE_BASE_READ)),
    ],
) -> dict:
    """获取单次 agent 执行的完整轨迹（含有序 steps）。"""
    run = (
        db.query(AgentRun)
        .filter(
            AgentRun.id == run_id,
            AgentRun.knowledge_base_id == context.knowledge_base.id,
        )
        .first()
    )
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    steps = (
        db.query(AgentStep)
        .filter(AgentStep.run_id == run_id)
        .order_by(AgentStep.step_index, AgentStep.created_at)
        .all()
    )
    return {
        "run": {
            "id": run.id,
            "query": run.query,
            "final_answer": run.final_answer,
            "mode": run.mode,
            "status": run.status.value,
            "steps_count": run.steps_count,
            "latency_ms": run.latency_ms,
            "total_input_tokens": run.total_input_tokens,
            "total_output_tokens": run.total_output_tokens,
            "total_cost": str(run.total_cost),
            "error_message": run.error_message,
            "created_at": run.created_at.isoformat() if run.created_at else None,
            "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        },
        "steps": [
            {
                "step_index": s.step_index,
                "step_type": s.step_type.value,
                "thought": s.thought,
                "tool_name": s.tool_name,
                "tool_args": s.tool_args,
                "tool_result": s.tool_result,
                "tool_success": s.tool_success,
                "input_tokens": s.input_tokens,
                "output_tokens": s.output_tokens,
                "latency_ms": s.latency_ms,
            }
            for s in steps
        ],
    }
