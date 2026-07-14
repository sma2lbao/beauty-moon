"""answer_question 在返回中透传 usage。"""
from types import SimpleNamespace

from app.graph import rag_graph
from app.services.llm import TokenUsage


def test_answer_question_includes_usage(monkeypatch):
    fake_usage = TokenUsage(input_tokens=5, output_tokens=6, model="m", provider="ark")

    class FakeGraph:
        def invoke(self, _state):
            return {
                "answer": "A",
                "sources": [],
                "prompt_version_id": None,
                "usage": fake_usage,
            }

    monkeypatch.setattr(rag_graph, "get_rag_graph", lambda: FakeGraph())
    result = rag_graph.answer_question("q", knowledge_base_id="kb")
    assert result["usage"] == fake_usage
