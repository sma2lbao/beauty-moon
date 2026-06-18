"""ReAct Agent - Reasoning and Acting loop."""
import json
import re
import time
from typing import Any, AsyncGenerator

from app.agent.base import Agent, AgentConfig, AgentResponse
from app.agent.tool import ToolResult
from app.services.llm import get_chat_model


REACT_SYSTEM_PROMPT = """You are a helpful AI assistant that uses tools to answer questions.

You follow the ReAct (Reasoning + Acting) pattern:
1. Think about what you need to do
2. Take an action (call a tool if needed)
3. Observe the result
4. Repeat until you can answer

Available tools:
{tool_schemas}

Respond in JSON format:
{{
    "thought": "What you're thinking about",
    "action": {{"name": "tool_name", "arguments": {{"arg1": "value1"}}}},
    "observation": null
}}

Or when done:
{{
    "thought": "I now have enough information to answer",
    "action": null,
    "observation": null,
    "answer": "Your final answer here"
}}

Today is {current_time}.
"""


class ReActAgent(Agent):
    """ReAct agent implementing the reasoning-acting loop.

    This agent:
    1. Thinks about what to do
    2. Calls a tool if needed
    3. Observes the result
    4. Repeats until it can answer
    """

    def __init__(self, config: AgentConfig):
        super().__init__(config)
        self.max_iterations = config.max_steps

    async def run(self, query: str) -> AgentResponse:
        """Execute query with ReAct loop."""
        start_time = time.time()
        tool_calls = []
        observation_history = []

        # Build system prompt
        tool_schemas = self.get_tool_schemas()
        schema_text = "\n".join([
            f"- {s['function']['name']}: {s['function']['description']}"
            for s in tool_schemas
        ]) if tool_schemas else "No tools available"

        from datetime import datetime
        system_prompt = REACT_SYSTEM_PROMPT.format(
            tool_schemas=schema_text,
            current_time=datetime.now().strftime("%Y-%m-%d"),
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": query},
        ]

        chat = get_chat_model()

        for iteration in range(self.max_iterations):
            # Call LLM
            response = chat.invoke(messages)
            content = response.content if hasattr(response, "content") else str(response)

            # Parse response
            parsed = self._parse_response(content)
            if parsed is None:
                # If we can't parse, try to get answer directly
                break

            thought = parsed.get("thought", "")
            action = parsed.get("action")
            answer = parsed.get("answer")
            observation = parsed.get("observation")

            # If we have an answer, we're done
            if answer:
                latency_ms = int((time.time() - start_time) * 1000)
                return AgentResponse(
                    answer=answer,
                    tool_calls=tool_calls,
                    steps=iteration + 1,
                    latency_ms=latency_ms,
                )

            # If we have an action, execute it
            if action:
                tool_name = action.get("name")
                args = action.get("arguments", {})
                tool = self.registry.get(tool_name)

                if tool:
                    result = await tool.execute(**args)
                    observation = result.output
                    tool_calls.append({
                        "tool": tool_name,
                        "args": args,
                        "result": result.output,
                        "success": result.success,
                    })

                    # Add observation to history and messages
                    observation_text = f"Observation: {observation}"
                    observation_history.append(observation_text)
                    messages.append({"role": "assistant", "content": content})
                    messages.append({"role": "user", "content": observation_text})
                else:
                    messages.append({"role": "assistant", "content": content})
                    messages.append({
                        "role": "user",
                        "content": f"Error: Tool '{tool_name}' not found"
                    })
            else:
                # No action, no answer - try direct response
                break

        # If loop ends without answer, get final response
        latency_ms = int((time.time() - start_time) * 1000)
        return AgentResponse(
            answer=content if content else "I couldn't find an answer.",
            tool_calls=tool_calls,
            steps=max(len(tool_calls), 1),
            latency_ms=latency_ms,
        )

    async def run_stream(self, query: str) -> AsyncGenerator[dict[str, Any], None]:
        """Execute with streaming response."""
        yield {"event": "start", "data": {"query": query}}

        tool_calls = []
        tool_schemas = self.get_tool_schemas()
        schema_text = "\n".join([
            f"- {s['function']['name']}: {s['function']['description']}"
            for s in tool_schemas
        ]) if tool_schemas else "No tools available"

        from datetime import datetime
        system_prompt = REACT_SYSTEM_PROMPT.format(
            tool_schemas=schema_text,
            current_time=datetime.now().strftime("%Y-%m-%d"),
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": query},
        ]

        chat = get_chat_model()

        for iteration in range(self.max_iterations):
            response = chat.invoke(messages)
            content = response.content if hasattr(response, "content") else str(response)

            yield {"event": "thought", "data": {"content": content}}

            parsed = self._parse_response(content)
            if parsed is None:
                break

            action = parsed.get("action")
            answer = parsed.get("answer")

            if answer:
                yield {"event": "done", "data": {"answer": answer, "tool_calls": tool_calls}}
                return

            if action:
                tool_name = action.get("name")
                args = action.get("arguments", {})
                tool = self.registry.get(tool_name)

                yield {"event": "tool_call", "data": {"tool": tool_name, "args": args}}

                if tool:
                    result = await tool.execute(**args)
                    tool_calls.append({
                        "tool": tool_name,
                        "args": args,
                        "result": result.output,
                    })
                    yield {"event": "tool_result", "data": {"result": result.output}}

                    messages.append({"role": "assistant", "content": content})
                    messages.append({"role": "user", "content": f"Observation: {result.output}"})
                else:
                    messages.append({"role": "assistant", "content": content})
                    messages.append({"role": "user", "content": f"Tool not found: {tool_name}"})

        yield {"event": "done", "data": {"answer": content, "tool_calls": tool_calls}}

    def _parse_response(self, response: str) -> dict[str, Any] | None:
        """Parse JSON response from LLM.

        Tries whole response first, then attempts to extract JSON objects
        with balanced braces from within the text.
        """
        if not response:
            return None

        # Try whole response as JSON
        try:
            return json.loads(response)
        except json.JSONDecodeError:
            pass

        # Try to extract JSON object with balanced braces
        start = response.find("{")
        while start != -1:
            depth = 0
            for i in range(start, len(response)):
                if response[i] == "{":
                    depth += 1
                elif response[i] == "}":
                    depth -= 1
                    if depth == 0:
                        try:
                            return json.loads(response[start : i + 1])
                        except json.JSONDecodeError:
                            break
            start = response.find("{", start + 1)

        return None
