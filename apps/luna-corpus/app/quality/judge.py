"""Quality judge abstraction and LLM-based implementation."""
import json
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Callable

from app.core.config import get_settings

settings = get_settings()

_JUDGE_PROMPT = """你是 RAG 回答质量评审。仅依据【检索上下文】判断【回答】的质量，输出 JSON。

【问题】
{question}

【检索上下文】
{context}

【回答】
{answer}

请对三项打 0 到 1 的分数：
- faithfulness：回答是否完全由检索上下文支撑（无幻觉）。
- answer_relevance：回答是否切合问题。
- citation_accuracy：回答引用/使用的内容是否确实来自检索上下文。

只输出如下 JSON，不要多余文字：
{{"faithfulness": <float>, "answer_relevance": <float>, "citation_accuracy": <float>, "rationale": "<一句话理由>"}}
"""


@dataclass
class QualityScores:
    """Structured judge output."""

    faithfulness: float | None
    answer_relevance: float | None
    citation_accuracy: float | None
    rationale: str | None = None
    model: str | None = None


def _format_context(sources: list[dict[str, Any]]) -> str:
    if not sources:
        return "（无检索上下文）"
    return "\n\n".join(
        f"[来源 {i + 1}] {s.get('chunk_content', '')}"
        for i, s in enumerate(sources)
    )


def parse_judge_response(raw: str) -> QualityScores:
    """Extract the JSON object from the model output. Raises ValueError on failure."""
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        raise ValueError("no JSON object in judge response")
    data = json.loads(match.group(0))
    return QualityScores(
        faithfulness=float(data["faithfulness"]),
        answer_relevance=float(data["answer_relevance"]),
        citation_accuracy=float(data["citation_accuracy"]),
        rationale=data.get("rationale"),
    )


class QualityJudge(ABC):
    """Scores a Q&A interaction for faithfulness/relevance/citation accuracy."""

    @abstractmethod
    def evaluate(
        self, question: str, answer: str, sources: list[dict[str, Any]]
    ) -> QualityScores:
        """Return structured quality scores. Raises on unrecoverable failure."""


class LLMQualityJudge(QualityJudge):
    """LLM-as-judge implementation using the configured chat model."""

    def __init__(
        self,
        generate: Callable[..., str] | None = None,
        model: str | None = None,
    ) -> None:
        if generate is None:
            from app.services.llm import generate_response

            generate = generate_response
        self._generate = generate
        self._model = model or settings.llm_provider.value

    def evaluate(
        self, question: str, answer: str, sources: list[dict[str, Any]]
    ) -> QualityScores:
        prompt = _JUDGE_PROMPT.format(
            question=question,
            context=_format_context(sources),
            answer=answer,
        )
        raw = self._generate(prompt=prompt, context=None)
        scores = parse_judge_response(raw)
        scores.model = self._model
        return scores


_instance: QualityJudge | None = None


def get_judge() -> QualityJudge:
    """Return the cached judge singleton, building it on first use."""
    global _instance
    if _instance is None:
        _instance = LLMQualityJudge()
    return _instance


def reset_judge_cache() -> None:
    """Drop the cached judge (test helper)."""
    global _instance
    _instance = None
