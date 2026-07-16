"""原生 function-calling 循环引擎：4 个模式共用。"""
import time
from dataclasses import dataclass

from app.agent.core.context import AgentRunContext
from app.agent.core.governance import check_step
from app.agent.core.trace import TraceRecorder
from app.agent.registry import ToolRegistry
from app.db.models import AgentRunStatus, AgentStepType
from app.services.llm import extract_usage


@dataclass
class LoopResult:
    """循环引擎的返回。"""

    answer: str
    status: AgentRunStatus
    steps: int


def _content(response) -> str:
    """从 LLM 响应中提取正文文本；无 content 属性时降级为 str()。"""
    return response.content if hasattr(response, "content") else str(response)


def _accumulate_usage(ctx: AgentRunContext, response, provider: str, model: str):
    """把一次 LLM 调用的 token 用量累加到 ctx；无用量则忽略。"""
    usage = extract_usage(response, provider, model)
    if usage is not None:
        ctx.total_input_tokens += usage.input_tokens
        ctx.total_output_tokens += usage.output_tokens
    return usage


async def run_tool_loop(
    *,
    chat,
    registry: ToolRegistry,
    ctx: AgentRunContext,
    trace: TraceRecorder,
    db,
    system_prompt: str,
    user_query: str,
    provider: str,
    model: str,
    single_shot: bool = False,
) -> LoopResult:
    """跑一个 function-calling 循环直至收敛或撞上治理上限。

    HaltSignal 不在此吞掉，交由调用方（管线）处理。
    """
    tools = registry.list_all()
    bound = chat.bind_tools([t.get_schema() for t in tools]) if tools else chat

    messages: list[dict] = [{"role": "system", "content": system_prompt}]
    if ctx.memory_history:
        messages.append({"role": "system", "content": ctx.memory_history})
    messages.append({"role": "user", "content": user_query})

    last_content = ""
    for step_index in range(ctx.max_steps):
        check_step(db, ctx, step_index)  # 触发 HaltSignal 时向上抛

        step_start = time.time()
        response = bound.invoke(messages)
        usage = _accumulate_usage(ctx, response, provider, model)
        last_content = _content(response)
        ctx.steps_count += 1
        trace.record_step(
            ctx,
            step_index=step_index,
            step_type=AgentStepType.REASONING,
            thought=last_content or None,
            input_tokens=usage.input_tokens if usage else None,
            output_tokens=usage.output_tokens if usage else None,
            latency_ms=int((time.time() - step_start) * 1000),
        )

        tool_calls = getattr(response, "tool_calls", None) or []
        if not tool_calls:
            trace.record_step(
                ctx,
                step_index=step_index,
                step_type=AgentStepType.FINAL,
                thought=last_content or None,
            )
            return LoopResult(last_content, AgentRunStatus.COMPLETED, ctx.steps_count)

        # 把 assistant 的工具调用意图加入消息历史
        messages.append(
            {"role": "assistant", "content": last_content, "tool_calls": tool_calls}
        )

        for call in tool_calls:
            name = call.get("name")
            args = call.get("args", call.get("arguments", {})) or {}
            call_id = call.get("id", name)
            trace.record_step(
                ctx,
                step_index=step_index,
                step_type=AgentStepType.TOOL_CALL,
                tool_name=name,
                tool_args=args,
            )
            tool_obj = registry.get(name)
            if tool_obj is None:
                result_text, success = f"Tool '{name}' not found", False
            else:
                result = await tool_obj.execute(**args)
                result_text = result.output if result.success else (result.error or "")
                success = result.success
            trace.record_step(
                ctx,
                step_index=step_index,
                step_type=AgentStepType.TOOL_RESULT,
                tool_name=name,
                tool_result=result_text,
                tool_success=success,
            )
            messages.append(
                {"role": "tool", "tool_call_id": call_id, "content": result_text}
            )

        if single_shot:
            # direct 模式：执行一轮工具后强制取最终答案
            final_resp = bound.invoke(messages)
            _accumulate_usage(ctx, final_resp, provider, model)
            final_text = _content(final_resp)
            ctx.steps_count += 1
            trace.record_step(
                ctx,
                step_index=step_index + 1,
                step_type=AgentStepType.FINAL,
                thought=final_text or None,
            )
            return LoopResult(final_text, AgentRunStatus.COMPLETED, ctx.steps_count)

    # 撞上 max_steps：用已有上下文的最后一次回答作为兜底
    return LoopResult(last_content, AgentRunStatus.HALTED_MAX_STEPS, ctx.steps_count)
