"""Synchronous interaction recording and evaluation sampling.

Recording is a side channel: any failure is logged and swallowed so the
Q&A request always succeeds.
"""
import random
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import QAInteraction
from app.observability.logging import get_logger
from app.observability.metrics import QA_INTERACTIONS_TOTAL

settings = get_settings()
logger = get_logger("luna.quality.recorder")


def record_interaction(
    db: Session,
    *,
    knowledge_base_id: str,
    question: str,
    answer: str,
    sources: list[dict[str, Any]],
    retrieval_mode: str | None = None,
    processing_time_ms: int | None = None,
    conversation_id: str | None = None,
    prompt_version_id: str | None = None,
) -> str | None:
    """Persist one Q&A interaction, returning its id (None on failure)."""
    try:
        interaction = QAInteraction(
            knowledge_base_id=knowledge_base_id,
            conversation_id=conversation_id,
            question=question,
            answer=answer,
            sources=sources,
            retrieval_mode=retrieval_mode,
            processing_time_ms=processing_time_ms,
            prompt_version_id=prompt_version_id,
        )
        db.add(interaction)
        db.flush()
        interaction_id = interaction.id
        db.commit()
        QA_INTERACTIONS_TOTAL.inc()
        return interaction_id
    except Exception:
        logger.warning(
            "record_interaction_failed",
            knowledge_base_id=knowledge_base_id,
            exc_info=True,
        )
        try:
            db.rollback()
        except Exception:
            pass
        return None


def should_evaluate(rand: float | None = None) -> bool:
    """Decide whether to trigger LLM evaluation for this interaction."""
    rate = settings.quality_eval_sample_rate
    if rate <= 0.0:
        return False
    if rate >= 1.0:
        return True
    draw = rand if rand is not None else random.random()
    return draw < rate
