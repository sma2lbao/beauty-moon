"""Plan-Execute Agent - 先规划再执行（基于共享循环引擎）。"""
from typing import Any, AsyncGenerator

from app.agent.base import Agent
from app.agent.core.llm_loop import LoopResult, run_tool_loop
from app.core.config import get_settings
from app.services.llm import get_chat_model

_SYSTEM_PROMPT = (
    "你是一个任务规划助手。先在心里列出完成任务所需的步骤，"
    "然后逐步调用工具执行，最后综合得出答案。可多次调用工具。"
)


def _provider_model():
    """从全局配置读取当前 provider 与模型名。"""
    s = get_settings()
    return s.llm_provider.value, s.ark_model


class PlanExecuteAgent(Agent):
    """先规划后执行。"""

    async def run(self, ctx, trace, db) -> LoopResult:
        provider, model = _provider_model()
        return await run_tool_loop(
            chat=get_chat_model(),
            registry=self.registry,
            ctx=ctx,
            trace=trace,
            db=db,
            system_prompt=_SYSTEM_PROMPT,
            user_query=ctx.query,
            provider=provider,
            model=model,
            single_shot=False,
        )

    async def run_stream(
        self, ctx, trace, db
    ) -> AsyncGenerator[dict[str, Any], None]:
        yield {"event": "run_start", "data": {"run_id": ctx.run_id}}
        result = await self.run(ctx, trace, db)
        yield {
            "event": "done",
            "data": {
                "answer": result.answer,
                "run_id": ctx.run_id,
                "steps": result.steps,
                "status": result.status.value,
            },
        }
