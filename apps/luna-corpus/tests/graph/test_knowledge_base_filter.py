"""Tests for knowledge-base filter propagation in RAG flows."""

from unittest.mock import patch

from app.graph import rag_graph


def test_retrieve_node_passes_knowledge_base_filter():
    with patch("app.graph.rag_graph.embed_text", return_value=[0.1]), patch(
        "app.graph.rag_graph.search_vectorstore",
        return_value=[],
    ) as search:
        rag_graph.retrieve_node({"question": "What?", "knowledge_base_id": "kb-1"})

    search.assert_called_once_with(
        query_embedding=[0.1],
        top_k=rag_graph.settings.retrieval_top_k,
        knowledge_base_id="kb-1",
    )


def test_answer_question_sets_knowledge_base_id_in_graph_state():
    class FakeGraph:
        def invoke(self, state):
            assert state["knowledge_base_id"] == "kb-1"
            return {"answer": "Answer", "sources": []}

    with patch("app.graph.rag_graph.get_rag_graph", return_value=FakeGraph()):
        result = rag_graph.answer_question("What?", knowledge_base_id="kb-1")

    assert result["answer"] == "Answer"
