"""Direct Agent - 单轮 + 可选一次工具调用（基于共享循环引擎）。"""
from typing import Any, AsyncGenerator

from app.agent.base import Agent
from app.agent.core.llm_loop import LoopResult, run_tool_loop
from app.core.config import get_settings
from app.services.llm import get_chat_model

_SYSTEM_PROMPT = "你是一个有用的助手，可按需调用工具。若无需工具，直接作答。"


def _provider_model():
    """从全局配置读取当前 provider 与模型名。"""
    s = get_settings()
    return s.llm_provider.value, s.ark_model


class DirectAgent(Agent):
    """单轮执行：最多一轮工具调用后强制收敛。"""

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
            single_shot=True,
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
