"""answer_question exposes retrieval_mode for interaction recording."""
from unittest.mock import patch

from app.graph import rag_graph


def test_answer_question_returns_retrieval_mode():
    fake_graph = type("G", (), {})()
    fake_graph.invoke = lambda state: {"answer": "A", "sources": []}
    with patch.object(rag_graph, "get_rag_graph", return_value=fake_graph):
        result = rag_graph.answer_question("Q", knowledge_base_id="kb-1")
    assert "retrieval_mode" in result
    assert result["retrieval_mode"] == rag_graph.settings.retrieval_mode.value


def test_answer_question_multi_turn_returns_retrieval_mode():
    fake_graph = type("G", (), {})()
    fake_graph.invoke = lambda state: {"answer": "A", "sources": []}
    with patch.object(rag_graph, "get_rag_graph", return_value=fake_graph):
        result = rag_graph.answer_question_multi_turn(
            question="Q", knowledge_base_id="kb-1", conversation_id="c-1"
        )
    assert "retrieval_mode" in result
    assert result["retrieval_mode"] == rag_graph.settings.retrieval_mode.value
