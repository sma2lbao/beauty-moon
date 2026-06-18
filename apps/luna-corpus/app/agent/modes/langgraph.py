"""LangGraph Agent - State machine workflow."""
import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator

from langgraph.graph import END, StateGraph

from app.agent.base import Agent, AgentConfig, AgentResponse
from app.agent.tool import ToolResult
from app.services.llm import get_chat_model


def _extract_tool_call_json(content: str) -> dict | None:
    """Extract a tool call JSON object from content using brace-depth tracking.

    Handles nested JSON objects (e.g., arguments containing nested dicts).
    """
    match = re.search(r"TOOL_CALL:\s*(\{)", content)
    if not match:
        return None

    start = match.start(1)
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(content)):
        ch = content[i]
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                json_str = content[start : i + 1]
                try:
                    return json.loads(json_str)
                except json.JSONDecodeError:
                    return None
    return None


@dataclass
class WorkflowState:
    """State for the LangGraph workflow."""

    query: str = ""
    tool_calls: list[dict] = field(default_factory=list)
    current_step: str = "start"
    classification: str = ""  # "simple" or "complex"
    intermediate_results: list[str] = field(default_factory=list)
    final_answer: str = ""
    steps_taken: int = 0


SYSTEM_PROMPT = """You are a task classifier. Classify the user's query into one of two categories:

1. "simple": The query can be answered directly or with a single tool call
2. "complex": The query requires multiple steps, reasoning, or conditional logic

User query: {query}

Respond with ONLY the classification word: simple or complex"""


class LangGraphAgent(Agent):
    """LangGraph-based agent with state machine workflow.

    Workflow:
    1. Classify query (simple vs complex)
    2. Route to appropriate handler
    3. Generate final response
    """

    def __init__(self, config: AgentConfig):
        super().__init__(config)
        self.graph = self._build_graph()

    def _build_graph(self) -> StateGraph:
        """Build the LangGraph state machine."""
        workflow = StateGraph(WorkflowState)

        # Add nodes
        workflow.add_node("classify", self._classify_node)
        workflow.add_node("simple_handler", self._simple_handler_node)
        workflow.add_node("complex_handler", self._complex_handler_node)
        workflow.add_node("final_response", self._final_response_node)

        # Add edges
        workflow.add_conditional_edges(
            "classify",
            lambda state: state.classification,
            {
                "simple": "simple_handler",
                "complex": "complex_handler",
            },
        )
        workflow.add_edge("simple_handler", "final_response")
        workflow.add_edge("complex_handler", "final_response")
        workflow.add_edge("final_response", END)

        workflow.set_entry_point("classify")

        return workflow.compile()

    async def _classify_node(self, state: WorkflowState) -> dict:
        """Classify the query as simple or complex."""
        prompt = SYSTEM_PROMPT.format(query=state.query)
        chat = get_chat_model()
        response = chat.invoke([{"role": "user", "content": prompt}])
        classification = (
            response.content.strip().lower()
            if hasattr(response, "content")
            else "simple"
        )

        if "complex" not in classification:
            classification = "simple"

        return {"classification": classification, "current_step": "classified"}

    async def _simple_handler_node(self, state: WorkflowState) -> dict:
        """Handle simple queries with DirectAgent-like logic."""
        tool_schemas = self.get_tool_schemas()
        tools_text = (
            "\n".join(
                [
                    f"- {s['function']['name']}: {s['function']['description']}"
                    for s in tool_schemas
                ]
            )
            if tool_schemas
            else "No tools"
        )

        prompt = f"""Answer the following query. If you need to use a tool, respond with:
TOOL_CALL: {{"name": "tool_name", "arguments": {{"arg1": "value1"}}}}

Available tools:
{tools_text}

Query: {state.query}

Respond directly or with a tool call."""

        chat = get_chat_model()
        response = chat.invoke([{"role": "user", "content": prompt}])
        content = response.content if hasattr(response, "content") else str(response)

        # Parse and execute tool call
        tool_call = _extract_tool_call_json(content)
        tool_calls = []

        if tool_call:
            tool_name = tool_call.get("name")
            args = tool_call.get("arguments", {})
            tool = self.registry.get(tool_name)

            if tool:
                result = await tool.execute(**args)
                tool_calls.append(
                    {
                        "tool": tool_name,
                        "args": args,
                        "result": result.output,
                        "success": result.success,
                    }
                )
                content = result.output

        return {
            "tool_calls": state.tool_calls + tool_calls,
            "intermediate_results": [content],
            "current_step": "simple_handled",
            "steps_taken": state.steps_taken + 1,
        }

    async def _complex_handler_node(self, state: WorkflowState) -> dict:
        """Handle complex queries with multi-step reasoning."""
        tool_schemas = self.get_tool_schemas()
        schema_list = [
            {
                "name": s["function"]["name"],
                "description": s["function"]["description"],
            }
            for s in tool_schemas
        ]

        prompt = f"""Analyze this complex query and determine the steps needed.

Query: {state.query}

Available tools: {schema_list}

Provide a brief plan and execute the first step.
Respond with:
PLAN: [list of steps]
RESULT: [result of first step]"""

        chat = get_chat_model()
        response = chat.invoke([{"role": "user", "content": prompt}])
        content = response.content if hasattr(response, "content") else str(response)

        # Simple implementation: return content as intermediate result
        return {
            "intermediate_results": state.intermediate_results + [content],
            "current_step": "complex_handled",
            "steps_taken": state.steps_taken + 1,
        }

    async def _final_response_node(self, state: WorkflowState) -> dict:
        """Generate final response from intermediate results."""
        context = (
            "\n".join(state.intermediate_results)
            if state.intermediate_results
            else ""
        )

        prompt = f"""Based on the following information, provide a comprehensive answer to the original query.

Original query: {state.query}

Information gathered:
{context}

Provide a clear and helpful answer."""

        chat = get_chat_model()
        response = chat.invoke([{"role": "user", "content": prompt}])
        final_answer = (
            response.content if hasattr(response, "content") else str(response)
        )

        return {"final_answer": final_answer, "current_step": "completed"}

    async def run(self, query: str) -> AgentResponse:
        """Execute query through the state machine."""
        start_time = time.time()

        initial_state = WorkflowState(query=query)

        # Use ainvoke to get the complete accumulated state
        final_state = await self.graph.ainvoke(initial_state)

        latency_ms = int((time.time() - start_time) * 1000)

        # ainvoke returns a dict-like object with all accumulated state
        if isinstance(final_state, dict):
            return AgentResponse(
                answer=final_state.get("final_answer", ""),
                tool_calls=final_state.get("tool_calls", []),
                steps=final_state.get("steps_taken", 0),
                latency_ms=latency_ms,
            )
        else:
            return AgentResponse(
                answer=getattr(final_state, "final_answer", str(final_state)),
                tool_calls=getattr(final_state, "tool_calls", []),
                steps=getattr(final_state, "steps_taken", 0),
                latency_ms=latency_ms,
            )

    async def run_stream(self, query: str) -> AsyncGenerator[dict[str, Any], None]:
        """Execute with streaming response."""
        yield {"event": "start", "data": {"query": query}}

        initial_state = WorkflowState(query=query)

        async for step_output in self.graph.astream(initial_state):
            for step_name, state_dict in step_output.items():
                yield {
                    "event": "step",
                    "data": {
                        "step": step_name,
                        "state": state_dict.get("current_step", ""),
                    },
                }

                if step_name == "final_response" and state_dict.get("final_answer"):
                    yield {
                        "event": "done",
                        "data": {
                            "answer": state_dict["final_answer"],
                            "tool_calls": state_dict.get("tool_calls", []),
                        },
                    }
                    return

        yield {"event": "done", "data": {"answer": "Processing complete"}}
