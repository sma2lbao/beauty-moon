"""Agent API routes."""
import json
import time
from typing import Any, AsyncGenerator

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.agent.factory import AgentFactory
from app.agent.registry import ToolRegistry
from app.agent.tool import Tool
from app.agent.tools import rag_search_tool, calculator_tool, current_time_tool
from app.core.config import AgentMode, get_settings

router = APIRouter(prefix="/api/v1/agent", tags=["agent"])

# Module-level registry for persisted tool registrations
_registered_tools: dict[str, Tool] = {}


# Request/Response Models
class AgentQueryRequest(BaseModel):
    """Agent query request."""
    query: str = Field(..., min_length=1, max_length=2000)
    mode: str = Field(default="direct", description="Agent mode: direct, react, plan, langgraph")
    available_tools: list[str] | None = Field(default=None, description="Tools to enable")
    stream: bool = Field(default=False, description="Enable streaming response")


class ToolCallInfo(BaseModel):
    """Information about a tool call."""
    tool: str
    args: dict[str, Any]
    result: str | None = None
    success: bool = True


class AgentQueryResponse(BaseModel):
    """Agent query response."""
    answer: str
    tool_calls: list[ToolCallInfo] = []
    mode: str
    steps: int = 0
    latency_ms: int = 0


class ToolInfo(BaseModel):
    """Tool information."""
    name: str
    description: str
    parameters_schema: dict[str, Any]


class ToolListResponse(BaseModel):
    """List of available tools."""
    tools: list[ToolInfo]


class ToolRegisterRequest(BaseModel):
    """Request to register a new tool."""
    name: str = Field(..., min_length=1)
    description: str = Field(..., min_length=1)
    parameters_schema: dict[str, Any]


def get_default_registry() -> ToolRegistry:
    """Get default tool registry with built-in tools and persisted registrations."""
    registry = ToolRegistry()
    registry.register(rag_search_tool)
    registry.register(calculator_tool)
    registry.register(current_time_tool)
    for tool in _registered_tools.values():
        registry.register(tool)
    return registry


@router.post("/query", response_model=AgentQueryResponse)
async def query(
    request: AgentQueryRequest,
) -> AgentQueryResponse:
    """Query the agent.

    Args:
        request: Query request

    Returns:
        Agent response
    """
    start_time = time.time()
    settings = get_settings()

    # Parse mode
    try:
        mode = AgentMode(request.mode.lower())
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid mode: {request.mode}")

    # Get tools
    registry = get_default_registry()

    # Filter by available_tools if specified
    if request.available_tools is not None:
        filtered_registry = ToolRegistry()
        for tool_name in request.available_tools:
            tool = registry.get(tool_name)
            if tool:
                filtered_registry.register(tool)
        registry = filtered_registry

    # Create agent
    agent = AgentFactory.create(
        mode=mode,
        tools=registry,
        max_steps=settings.agent_max_steps,
    )

    # Execute
    result = await agent.run(request.query)

    latency_ms = int((time.time() - start_time) * 1000)

    return AgentQueryResponse(
        answer=result.answer,
        tool_calls=[
            ToolCallInfo(
                tool=tc["tool"],
                args=tc["args"],
                result=tc.get("result"),
                success=tc.get("success", True),
            )
            for tc in result.tool_calls
        ],
        mode=request.mode,
        steps=result.steps,
        latency_ms=latency_ms,
    )


async def agent_stream_generator(
    query: str,
    mode: AgentMode,
    registry: ToolRegistry,
) -> AsyncGenerator[str, None]:
    """Generate SSE events for streaming agent response."""
    try:
        settings = get_settings()
        agent = AgentFactory.create(
            mode=mode,
            tools=registry,
            max_steps=settings.agent_max_steps,
        )

        async for event in agent.run_stream(query):
            yield f"data: {json.dumps(event)}\n\n"

    except Exception as e:
        yield f"data: {json.dumps({'event': 'error', 'data': str(e)})}\n\n"


@router.post("/stream")
async def stream_query(request: AgentQueryRequest):
    """Stream agent query response.

    Args:
        request: Query request

    Returns:
        StreamingResponse
    """
    try:
        mode = AgentMode(request.mode.lower())
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid mode: {request.mode}")

    registry = get_default_registry()
    if request.available_tools is not None:
        filtered_registry = ToolRegistry()
        for tool_name in request.available_tools:
            tool = registry.get(tool_name)
            if tool:
                filtered_registry.register(tool)
        registry = filtered_registry

    return StreamingResponse(
        agent_stream_generator(request.query, mode, registry),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/tools", response_model=ToolListResponse)
async def list_tools() -> ToolListResponse:
    """List all available tools.

    Returns:
        List of tools
    """
    registry = get_default_registry()
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
async def register_tool(request: ToolRegisterRequest):
    """Register a new tool.

    Args:
        request: Tool registration request

    Returns:
        Success message
    """
    tool = Tool(
        name=request.name,
        description=request.description,
        parameters_schema=request.parameters_schema,
    )

    _registered_tools[request.name] = tool

    return {"message": f"Tool '{request.name}' registered", "name": request.name}


@router.get("/modes")
async def list_modes():
    """List available agent modes.

    Returns:
        List of modes
    """
    return {
        "modes": [
            {"mode": "direct", "description": "Direct execution - single LLM call"},
            {"mode": "react", "description": "ReAct loop - reasoning and acting"},
            {"mode": "plan", "description": "Plan-then-Execute - plan first, execute second"},
            {"mode": "langgraph", "description": "State machine workflow"},
        ]
    }
