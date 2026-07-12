"""Unit tests for the LLM quality judge."""
import pytest

from app.quality.judge import (
    LLMQualityJudge,
    QualityScores,
    parse_judge_response,
)


def test_parse_valid_json():
    raw = (
        '{"faithfulness": 0.9, "answer_relevance": 0.8, '
        '"citation_accuracy": 0.7, "rationale": "ok"}'
    )
    scores = parse_judge_response(raw)
    assert scores.faithfulness == 0.9
    assert scores.answer_relevance == 0.8
    assert scores.citation_accuracy == 0.7
    assert scores.rationale == "ok"


def test_parse_json_embedded_in_text():
    raw = 'Here is my judgement:\n{"faithfulness": 1.0, "answer_relevance": 1.0, "citation_accuracy": 1.0}'
    scores = parse_judge_response(raw)
    assert scores.faithfulness == 1.0


def test_parse_invalid_raises():
    with pytest.raises(ValueError):
        parse_judge_response("no json here")


def test_judge_uses_injected_generate(monkeypatch):
    def fake_generate(prompt, context=None):
        assert "Q?" in prompt
        return '{"faithfulness": 0.5, "answer_relevance": 0.5, "citation_accuracy": 0.5, "rationale": "r"}'

    judge = LLMQualityJudge(generate=fake_generate, model="fake-model")
    scores = judge.evaluate(
        "Q?", "A.", [{"document_id": "d1", "chunk_content": "c", "relevance_score": 0.9}]
    )
    assert isinstance(scores, QualityScores)
    assert scores.faithfulness == 0.5
    assert scores.model == "fake-model"