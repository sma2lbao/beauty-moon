"""Tests for built-in tools."""

from unittest.mock import patch

from app.agent.tools.calculator import calculator_tool, safe_eval
from app.agent.tools.rag_search import create_rag_search_tool
from app.agent.tools.time_tool import current_time_tool


def test_calculator_basic():
    """Test basic calculator operations."""
    assert safe_eval("2 + 3") == 5
    assert safe_eval("10 - 4") == 6
    assert safe_eval("3 * 4") == 12
    assert safe_eval("15 / 3") == 5


def test_calculator_advanced():
    """Test advanced calculator operations."""
    assert safe_eval("2 + 3 * 4") == 14
    assert safe_eval("(2 + 3) * 4") == 20
    assert safe_eval("2 ** 3") == 8
    assert safe_eval("10 % 3") == 1


def test_calculator_negative():
    """Test calculator with negative results."""
    assert safe_eval("5 - 10") == -5
    assert safe_eval("-5 + 3") == -2


def test_calculator_tool():
    """Test calculator tool."""
    result = calculator_tool.executor(expression="2 + 3 * 4")
    assert result == 14


def test_current_time_tool():
    """Test current time tool."""
    result = current_time_tool.executor()
    assert len(result) > 0
    assert "-" in result or "/" in result


def test_current_time_custom_format():
    """Test current time with custom format."""
    result = current_time_tool.executor(format="%Y-%m-%d")
    assert len(result) == 10
    assert result.count("-") == 2


def test_create_rag_search_tool_passes_knowledge_base_filter():
    rag_tool = create_rag_search_tool("kb-1")

    with (
        patch("app.agent.tools.rag_search.embed_text", return_value=[0.1]),
        patch(
            "app.agent.tools.rag_search.hybrid_search",
            return_value=[
                {
                    "chunk_id": "chunk-1",
                    "document_id": "doc-1",
                    "content": "Relevant content",
                    "score": 0.2,
                }
            ],
        ) as search,
    ):
        result = rag_tool.executor(query="What?", top_k=3)

    search.assert_called_once_with(
        "What?", [0.1], top_k=3, knowledge_base_id="kb-1"
    )
    assert "Relevant content" in result


def test_rag_search_tool_schema_does_not_expose_knowledge_base_id():
    rag_tool = create_rag_search_tool("kb-1")

    properties = rag_tool.parameters_schema["properties"]

    assert "query" in properties
    assert "top_k" in properties
    assert "knowledge_base_id" not in properties


def test_rag_search_tool_handles_empty_results():
    rag_tool = create_rag_search_tool("kb-1")

    with (
        patch("app.agent.tools.rag_search.embed_text", return_value=[0.1]),
        patch("app.agent.tools.rag_search.hybrid_search", return_value=[]),
    ):
        result = rag_tool.executor(query="What?")

    assert result == "No relevant documents found in the knowledge base."


def test_rag_search_tool_handles_vectorstore_error():
    rag_tool = create_rag_search_tool("kb-1")

    with (
        patch("app.agent.tools.rag_search.embed_text", return_value=[0.1]),
        patch(
            "app.agent.tools.rag_search.hybrid_search",
            side_effect=RuntimeError("backend unavailable"),
        ),
    ):
        result = rag_tool.executor(query="What?")

    assert result == "Error searching knowledge base: backend unavailable"
