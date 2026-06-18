"""Plan-then-Execute Agent."""
import json
import re
import time
from datetime import datetime
from typing import Any, AsyncGenerator

from app.agent.base import Agent, AgentConfig, AgentResponse
from app.services.llm import get_chat_model


PLAN_PROMPT = """You are a task planner. Given a user query, create a plan to accomplish it.

The plan should be a JSON array of steps, where each step has:
- "tool": tool name (or "final_answer" for the last step)
- "arguments": tool arguments (or null)
- "reasoning": why this step is needed

Available tools:
{tool_schemas}

Respond ONLY with valid JSON in this format:
[
    {{"tool": "tool_name", "arguments": {{"arg1": "value"}}, "reasoning": "Why this step"}},
    ...
]

Today is {current_time}.
"""


EXECUTE_PROMPT = """You are a helpful AI assistant. A plan was executed and here are the results:

{results}

Based on these results, provide a final answer to the original question.
"""


class PlanExecuteAgent(Agent):
    """Plan-then-Execute agent.

    This agent:
    1. Generates a plan (first LLM call)
    2. Executes steps in order (second LLM call)
    3. Returns the final answer
    """

    async def run(self, query: str) -> AgentResponse:
        """Execute query with planning first."""
        start_time = time.time()
        tool_calls = []

        # Phase 1: Generate plan
        tool_schemas = self.get_tool_schemas()
        schema_text = "\n".join([
            f"- {s['function']['name']}: {s['function']['description']}"
            for s in tool_schemas
        ]) if tool_schemas else "No tools available"

        plan_prompt = PLAN_PROMPT.format(
            tool_schemas=schema_text,
            current_time=datetime.now().strftime("%Y-%m-%d"),
        )

        messages = [
            {"role": "system", "content": plan_prompt},
            {"role": "user", "content": query},
        ]

        chat = get_chat_model()
        plan_response = chat.invoke(messages)
        plan_content = plan_response.content if hasattr(plan_response, "content") else str(plan_response)

        # Parse plan
        plan = self._parse_plan(plan_content)
        if plan is None:
            # Fallback: treat as direct response
            latency_ms = int((time.time() - start_time) * 1000)
            return AgentResponse(
                answer=plan_content,
                tool_calls=[],
                steps=0,
                latency_ms=latency_ms,
            )

        # Phase 2: Execute plan
        results_text = []
        for i, step in enumerate(plan):
            tool_name = step.get("tool")
            args = step.get("arguments", {})

            if tool_name == "final_answer":
                break

            tool = self.registry.get(tool_name)
            if tool:
                result = await tool.execute(**args)
                tool_calls.append({
                    "tool": tool_name,
                    "args": args,
                    "result": result.output,
                    "success": result.success,
                })
                results_text.append(f"Step {i+1} ({tool_name}): {result.output}")
            else:
                results_text.append(f"Step {i+1} ({tool_name}): Tool not found")

        # Phase 3: Generate final answer
        execute_prompt = EXECUTE_PROMPT.format(
            results="\n".join(results_text) if results_text else "No steps were executed",
        )

        final_messages = [
            {"role": "system", "content": execute_prompt},
            {"role": "user", "content": query},
        ]

        final_response = chat.invoke(final_messages)
        final_answer = final_response.content if hasattr(final_response, "content") else str(final_response)

        latency_ms = int((time.time() - start_time) * 1000)
        return AgentResponse(
            answer=final_answer,
            tool_calls=tool_calls,
            steps=len(plan),
            latency_ms=latency_ms,
        )

    async def run_stream(self, query: str) -> AsyncGenerator[dict[str, Any], None]:
        """Execute with streaming response."""
        yield {"event": "start", "data": {"query": query}}
        yield {"event": "phase", "data": {"phase": "planning"}}

        tool_schemas = self.get_tool_schemas()
        schema_text = "\n".join([
            f"- {s['function']['name']}: {s['function']['description']}"
            for s in tool_schemas
        ]) if tool_schemas else "No tools available"

        plan_prompt = PLAN_PROMPT.format(
            tool_schemas=schema_text,
            current_time=datetime.now().strftime("%Y-%m-%d"),
        )

        messages = [
            {"role": "system", "content": plan_prompt},
            {"role": "user", "content": query},
        ]

        chat = get_chat_model()
        plan_response = chat.invoke(messages)
        plan_content = plan_response.content if hasattr(plan_response, "content") else str(plan_response)

        yield {"event": "plan", "data": {"plan": plan_content}}

        plan = self._parse_plan(plan_content)
        if plan is None:
            yield {"event": "done", "data": {"answer": plan_content}}
            return

        yield {"event": "phase", "data": {"phase": "executing"}}

        tool_calls = []
        results_text = []

        for i, step in enumerate(plan):
            yield {"event": "step", "data": {"step": i + 1, "total": len(plan)}}

            tool_name = step.get("tool")
            args = step.get("arguments", {})

            if tool_name == "final_answer":
                break

            tool = self.registry.get(tool_name)
            if tool:
                result = await tool.execute(**args)
                tool_calls.append({
                    "tool": tool_name,
                    "args": args,
                    "result": result.output,
                })
                results_text.append(f"Step {i+1}: {result.output}")
                yield {"event": "tool_result", "data": {"result": result.output}}
            else:
                results_text.append(f"Step {i+1}: Tool not found")

        yield {"event": "phase", "data": {"phase": "finalizing"}}

        execute_prompt = EXECUTE_PROMPT.format(
            results="\n".join(results_text) if results_text else "No steps were executed",
        )

        final_messages = [
            {"role": "system", "content": execute_prompt},
            {"role": "user", "content": query},
        ]

        final_response = chat.invoke(final_messages)
        final_answer = final_response.content if hasattr(final_response, "content") else str(final_response)

        yield {"event": "done", "data": {"answer": final_answer, "tool_calls": tool_calls}}

    def _parse_plan(self, response: str) -> list[dict[str, Any]] | None:
        """Parse plan from LLM response."""
        # Try to extract JSON array
        json_match = re.search(r'\[[\s\S]*\]', response)
        if json_match:
            try:
                return json.loads(json_match.group())
            except json.JSONDecodeError:
                pass

        # Try whole response
        try:
            parsed = json.loads(response)
            if isinstance(parsed, list):
                return parsed
        except json.JSONDecodeError:
            pass

        return None
