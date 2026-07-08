"""rag_search 工具 filters 透传测试。"""
from unittest.mock import patch

from app.agent.tools.rag_search import create_rag_search_tool
from app.metadata.schema import FieldType
from app.retrieval.filters import FilterOp, MetadataCondition, MetadataFilter


def test_rag_search_tool_passes_filters():
    f = MetadataFilter(conditions=[
        MetadataCondition(key="category", op=FilterOp.EQ, value="合同")
    ])
    ft = {"category": FieldType.ENUM}
    tool = create_rag_search_tool("kb1", filters=f, field_types=ft)
    with patch(
        "app.agent.tools.rag_search.embed_text", return_value=[0.1]
    ), patch(
        "app.agent.tools.rag_search.hybrid_search", return_value=[]
    ) as hs:
        tool.executor(query="q")
    _, kwargs = hs.call_args
    assert kwargs["filters"] is f
    assert kwargs["field_types"] is ft


def test_rag_search_tool_default_no_filters():
    tool = create_rag_search_tool("kb1")
    with patch(
        "app.agent.tools.rag_search.embed_text", return_value=[0.1]
    ), patch(
        "app.agent.tools.rag_search.hybrid_search", return_value=[]
    ) as hs:
        tool.executor(query="q")
    _, kwargs = hs.call_args
    assert kwargs.get("filters") is None
