"""Direct Agent - single tool call execution."""
import time
from typing import Any, AsyncGenerator

from app.agent.base import Agent, AgentConfig, AgentResponse
from app.agent.tool import ToolResult
from app.services.llm import get_chat_model


SYSTEM_PROMPT = """You are a helpful AI assistant with access to tools.
When a user asks a question, decide if you need to use a tool or can answer directly.

Available tools:
{tool_schemas}

Respond in the following format for tool calls:
TOOL_CALL: {{"name": "tool_name", "arguments": {{"arg1": "value1"}}}}
If no tool is needed, respond directly with your answer.

Today is {current_time}.
"""


class DirectAgent(Agent):
    """Direct agent that makes a single LLM call.

    This agent:
    1. Formats the prompt with available tools
    2. Calls the LLM once
    3. Executes any requested tool
    4. Returns the result
    """

    async def run(self, query: str) -> AgentResponse:
        """Execute a single-turn query."""
        start_time = time.time()
        tool_calls: list[dict[str, Any]] = []

        # Get tool schemas for prompt
        tool_schemas = self.get_tool_schemas()
        schema_text = "\n".join([
            f"- {s['function']['name']}: {s['function']['description']}"
            for s in tool_schemas
        ]) if tool_schemas else "No tools available"

        from datetime import datetime

        prompt = SYSTEM_PROMPT.format(
            tool_schemas=schema_text,
            current_time=datetime.now().strftime("%Y-%m-%d"),
        )

        # Build messages
        messages = [
            {"role": "system", "content": prompt},
            {"role": "user", "content": query},
        ]

        # Call LLM
        chat = get_chat_model()
        response = chat.invoke(messages)
        content = response.content if hasattr(response, "content") else str(response)

        # Parse tool call from response
        tool_call = self._parse_tool_call(content)
        if tool_call:
            tool_name = tool_call["name"]
            args = tool_call["arguments"]
            tool = self.registry.get(tool_name)

            if tool:
                result = await tool.execute(**args)
                tool_calls.append({
                    "tool": tool_name,
                    "args": args,
                    "result": result.output,
                    "success": result.success,
                })
                # Generate final answer with tool result
                content = self._generate_final_response(content, result)

        latency_ms = int((time.time() - start_time) * 1000)

        return AgentResponse(
            answer=content,
            tool_calls=tool_calls,
            steps=len(tool_calls) + 1,
            latency_ms=latency_ms,
        )

    async def run_stream(self, query: str) -> AsyncGenerator[dict[str, Any], None]:
        """Execute with streaming response."""
        yield {"event": "start", "data": {"query": query}}

        tool_calls: list[dict[str, Any]] = []
        tool_schemas = self.get_tool_schemas()
        schema_text = "\n".join([
            f"- {s['function']['name']}: {s['function']['description']}"
            for s in tool_schemas
        ]) if tool_schemas else "No tools available"

        from datetime import datetime

        prompt = SYSTEM_PROMPT.format(
            tool_schemas=schema_text,
            current_time=datetime.now().strftime("%Y-%m-%d"),
        )

        messages = [
            {"role": "system", "content": prompt},
            {"role": "user", "content": query},
        ]

        chat = get_chat_model()
        response = chat.invoke(messages)
        content = response.content if hasattr(response, "content") else str(response)

        # Parse tool call
        tool_call = self._parse_tool_call(content)
        if tool_call:
            tool_name = tool_call["name"]
            args = tool_call["arguments"]
            tool = self.registry.get(tool_name)

            yield {"event": "tool_call", "data": {"tool": tool_name, "args": args}}

            if tool:
                result = await tool.execute(**args)
                tool_calls.append({
                    "tool": tool_name,
                    "args": args,
                    "result": result.output,
                    "success": result.success,
                })
                yield {"event": "tool_result", "data": {"tool": tool_name, "result": result.output}}
                content = self._generate_final_response(content, result)

        yield {"event": "token", "data": {"content": content}}
        yield {
            "event": "done",
            "data": {
                "answer": content,
                "tool_calls": tool_calls,
                "steps": len(tool_calls) + 1,
            },
        }

    def _parse_tool_call(self, response: str) -> dict[str, Any] | None:
        """Parse tool call from LLM response."""
        import json

        # Look for TOOL_CALL: marker
        idx = response.find("TOOL_CALL:")
        if idx == -1:
            return None

        # Find the opening brace after TOOL_CALL:
        brace_start = response.find("{", idx)
        if brace_start == -1:
            return None

        # Match balanced braces
        depth = 0
        brace_end = brace_start
        for i in range(brace_start, len(response)):
            if response[i] == "{":
                depth += 1
            elif response[i] == "}":
                depth -= 1
                if depth == 0:
                    brace_end = i + 1
                    break

        json_str = response[brace_start:brace_end]
        try:
            return json.loads(json_str)
        except json.JSONDecodeError:
            pass
        return None

    def _generate_final_response(self, original: str, tool_result: ToolResult) -> str:
        """Generate final response using tool result."""
        # Simple implementation: return tool result if present
        if tool_result.success:
            # Check if original response mentions the tool call
            if "TOOL_CALL:" in original:
                # Extract explanation before TOOL_CALL
                parts = original.split("TOOL_CALL:")
                explanation = parts[0].strip()
                if explanation:
                    return f"{explanation}\n\nResult: {tool_result.output}"
                return tool_result.output
        return original
