"""原生 function-calling 循环引擎：4 个模式共用。"""
import time
from dataclasses import dataclass

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)

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

    HaltSignal 不在此吞掉，交由调用方（管线）处理。使用 LangChain 原生消息对象
    维护对话历史，避免不同 provider（ARK / Ollama）在 tool_calls wire 格式上的兼容差异。
    """
    tools = registry.list_all()
    bound = chat.bind_tools([t.get_schema() for t in tools]) if tools else chat

    messages: list[BaseMessage] = [SystemMessage(content=system_prompt)]
    if ctx.memory_history:
        messages.append(SystemMessage(content=ctx.memory_history))
    messages.append(HumanMessage(content=user_query))

    last_content = ""
    for step_index in range(ctx.max_steps):
        check_step(db, ctx, step_index)  # 触发 HaltSignal 时向上抛

        step_start = time.time()
        response = await bound.ainvoke(messages)
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

        # 用 AIMessage 承载 assistant 的 tool_calls，交给下一轮 ainvoke 时
        # LangChain 会按 provider wire 格式序列化，避免 raw dict 的跨版本兼容问题。
        messages.append(AIMessage(content=last_content, tool_calls=tool_calls))

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
                ToolMessage(tool_call_id=call_id, content=result_text)
            )

        if single_shot:
            # direct 模式：执行一轮工具后强制取最终答案；
            # 先做治理预检，避免二次调用绕过 timeout / quota 硬闸。
            check_step(db, ctx, step_index + 1)
            final_start = time.time()
            final_resp = await bound.ainvoke(messages)
            final_usage = _accumulate_usage(ctx, final_resp, provider, model)
            final_text = _content(final_resp)
            ctx.steps_count += 1
            trace.record_step(
                ctx,
                step_index=step_index + 1,
                step_type=AgentStepType.FINAL,
                thought=final_text or None,
                input_tokens=final_usage.input_tokens if final_usage else None,
                output_tokens=final_usage.output_tokens if final_usage else None,
                latency_ms=int((time.time() - final_start) * 1000),
            )
            return LoopResult(final_text, AgentRunStatus.COMPLETED, ctx.steps_count)

    # 撞上 max_steps：按 spec §4.1，用已有工具结果强制不带 tools 收敛一次 final answer。
    # 若兜底调用失败则退化为最后一次 assistant 正文（可能为空串），
    # 确保 run 能正常终态化。
    try:
        final_msgs = [
            *messages,
            SystemMessage(
                content=(
                    "步数已达上限，请基于已有工具结果直接给出最终答复，不再调用工具。"
                    "如果无法给出可靠答复，请说明未能完成的原因。"
                )
            ),
        ]
        final_start = time.time()
        final_resp = await chat.ainvoke(final_msgs)  # 使用未绑定 tools 的原生 chat
        final_usage = _accumulate_usage(ctx, final_resp, provider, model)
        final_text = _content(final_resp)
        ctx.steps_count += 1
        trace.record_step(
            ctx,
            step_index=ctx.max_steps,
            step_type=AgentStepType.FINAL,
            thought=final_text or None,
            input_tokens=final_usage.input_tokens if final_usage else None,
            output_tokens=final_usage.output_tokens if final_usage else None,
            latency_ms=int((time.time() - final_start) * 1000),
        )
        return LoopResult(
            final_text or last_content,
            AgentRunStatus.HALTED_MAX_STEPS,
            ctx.steps_count,
        )
    except Exception:  # noqa: BLE001 - 兜底不能因 LLM 再次异常而崩掉整个 run
        return LoopResult(
            last_content, AgentRunStatus.HALTED_MAX_STEPS, ctx.steps_count
        )
