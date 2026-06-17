"""Tests for built-in tools."""
import pytest
from app.agent.tools.rag_search import rag_search_tool
from app.agent.tools.calculator import calculator_tool, safe_eval
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
