"""Agent API routes."""
import json
import time
from typing import Annotated, Any, AsyncGenerator

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.agent.factory import AgentFactory
from app.agent.registry import ToolRegistry
from app.agent.tool import Tool
from app.agent.tools import calculator_tool, create_rag_search_tool, current_time_tool
from app.api.auth import AuthenticatedRequestContext, require_permission
from app.auth.permissions import PermissionSlug
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


def get_default_registry(knowledge_base_id: str) -> ToolRegistry:
    """Get default tool registry with built-in tools and persisted registrations."""
    registry = ToolRegistry()
    registry.register(create_rag_search_tool(knowledge_base_id))
    registry.register(calculator_tool)
    registry.register(current_time_tool)
    for tool in _registered_tools.values():
        registry.register(tool)
    return registry


def filter_registry(registry: ToolRegistry, available_tools: list[str] | None) -> ToolRegistry:
    """Filter a registry by requested tool names, preserving empty-list semantics."""
    if available_tools is None:
        return registry

    filtered_registry = ToolRegistry()
    for tool_name in available_tools:
        tool = registry.get(tool_name)
        if tool:
            filtered_registry.register(tool)
    return filtered_registry


@router.post("/query", response_model=AgentQueryResponse)
async def query(
    request: AgentQueryRequest,
    context: Annotated[
        AuthenticatedRequestContext,
        Depends(require_permission(PermissionSlug.QA_QUERY)),
    ],
) -> AgentQueryResponse:
    """Query the agent.

    Args:
        request: Query request
        context: Request context with knowledge base scope

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
    registry = filter_registry(
        get_default_registry(context.knowledge_base.id),
        request.available_tools,
    )

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
async def stream_query(
    request: AgentQueryRequest,
    context: Annotated[
        AuthenticatedRequestContext,
        Depends(require_permission(PermissionSlug.QA_QUERY)),
    ],
):
    """Stream agent query response.

    Args:
        request: Query request
        context: Request context with knowledge base scope

    Returns:
        StreamingResponse
    """
    try:
        mode = AgentMode(request.mode.lower())
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid mode: {request.mode}")

    registry = filter_registry(
        get_default_registry(context.knowledge_base.id),
        request.available_tools,
    )

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
async def list_tools(
    context: Annotated[
        AuthenticatedRequestContext,
        Depends(require_permission(PermissionSlug.KNOWLEDGE_BASE_READ)),
    ],
) -> ToolListResponse:
    """List all available tools.

    Args:
        context: Request context with knowledge base scope

    Returns:
        List of tools
    """
    registry = get_default_registry(context.knowledge_base.id)
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
async def register_tool(
    request: ToolRegisterRequest,
    context: Annotated[
        AuthenticatedRequestContext,
        Depends(require_permission(PermissionSlug.KNOWLEDGE_BASE_MANAGE)),
    ],
):
    """Register a new tool.

    Args:
        request: Tool registration request
        context: Request context with knowledge base scope

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
async def list_modes(
    context: Annotated[
        AuthenticatedRequestContext,
        Depends(require_permission(PermissionSlug.KNOWLEDGE_BASE_READ)),
    ],
):
    """List available agent modes.

    Args:
        context: Request context with knowledge base scope

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
