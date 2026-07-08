"""retrieve_node 使用 filters 透传的单元测试。"""
from unittest.mock import patch

from app.graph.rag_graph import retrieve_node
from app.metadata.schema import FieldType
from app.retrieval.filters import FilterOp, MetadataCondition, MetadataFilter


def test_retrieve_node_passes_filters_to_hybrid_search():
    f = MetadataFilter(conditions=[
        MetadataCondition(key="category", op=FilterOp.EQ, value="合同")
    ])
    state = {
        "question": "q",
        "knowledge_base_id": "kb1",
        "filters": f.model_dump(),
        "field_types": {"category": "enum"},
    }
    with patch("app.graph.rag_graph.embed_text", return_value=[0.1]), \
         patch("app.graph.rag_graph.hybrid_search", return_value=[]) as hs, \
         patch(
             "app.graph.rag_graph.validate_retrieved_docs_for_knowledge_base",
             side_effect=lambda docs, kb: docs,
         ):
        retrieve_node(state)
    _, kwargs = hs.call_args
    assert isinstance(kwargs["filters"], MetadataFilter)
    assert kwargs["field_types"] == {"category": FieldType.ENUM}


def test_retrieve_node_no_filters_passes_none():
    state = {"question": "q", "knowledge_base_id": "kb1"}
    with patch("app.graph.rag_graph.embed_text", return_value=[0.1]), \
         patch("app.graph.rag_graph.hybrid_search", return_value=[]) as hs, \
         patch(
             "app.graph.rag_graph.validate_retrieved_docs_for_knowledge_base",
             side_effect=lambda docs, kb: docs,
         ):
        retrieve_node(state)
    _, kwargs = hs.call_args
    assert kwargs.get("filters") is None
