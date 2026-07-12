"""Background LLM evaluation task.

Mirrors the ingestion index-task pattern: runs in its own DB session and
never raises into the caller; failures land as EvaluationStatus.FAILED.
"""
from sqlalchemy.orm import Session

from app.db.database import SessionLocal
from app.db.models import EvaluationStatus, QAEvaluation, QAInteraction
from app.observability.logging import get_logger
from app.observability.metrics import QA_EVALUATIONS_TOTAL
from app.quality.judge import QualityJudge, get_judge

logger = get_logger("luna.quality.tasks")


def create_pending_evaluation(db: Session, interaction_id: str) -> str | None:
    """Create a pending QAEvaluation row, returning its id (None on failure)."""
    try:
        evaluation = QAEvaluation(
            interaction_id=interaction_id,
            status=EvaluationStatus.PENDING,
        )
        db.add(evaluation)
        db.flush()
        eval_id = evaluation.id
        db.commit()
        return eval_id
    except Exception:
        logger.warning(
            "create_pending_evaluation_failed",
            interaction_id=interaction_id,
            exc_info=True,
        )
        try:
            db.rollback()
        except Exception:
            pass
        return None


def _run_eval_task(evaluation_id: str, judge: QualityJudge | None = None) -> None:
    """Background task: score an interaction and persist terminal status."""
    judge = judge or get_judge()
    db = SessionLocal()
    try:
        evaluation = db.get(QAEvaluation, evaluation_id)
        if evaluation is None:
            logger.warning("evaluation_missing", evaluation_id=evaluation_id)
            return
        interaction = db.get(QAInteraction, evaluation.interaction_id)
        if interaction is None:
            logger.warning(
                "interaction_missing", evaluation_id=evaluation_id
            )
            evaluation.status = EvaluationStatus.FAILED
            db.commit()
            QA_EVALUATIONS_TOTAL.labels(status="failed").inc()
            return

        try:
            scores = judge.evaluate(
                interaction.question, interaction.answer, interaction.sources
            )
            evaluation.faithfulness = scores.faithfulness
            evaluation.answer_relevance = scores.answer_relevance
            evaluation.citation_accuracy = scores.citation_accuracy
            evaluation.judge_model = scores.model
            evaluation.rationale = scores.rationale
            evaluation.status = EvaluationStatus.COMPLETED
            db.commit()
            QA_EVALUATIONS_TOTAL.labels(status="completed").inc()
        except Exception:
            logger.warning(
                "evaluation_failed", evaluation_id=evaluation_id, exc_info=True
            )
            evaluation.status = EvaluationStatus.FAILED
            db.commit()
            QA_EVALUATIONS_TOTAL.labels(status="failed").inc()
    finally:
        db.close()
