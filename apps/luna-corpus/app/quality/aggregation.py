"""Read-only quality aggregation for the monitoring summary endpoint."""
from datetime import datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.models import (
    EvaluationStatus,
    FeedbackRating,
    QAEvaluation,
    QAFeedback,
    QAInteraction,
)


def summarize_quality(
    db: Session, knowledge_base_id: str, days: int = 7
) -> dict:
    """Aggregate interactions, feedback and evaluations for a KB / time window."""
    since = datetime.utcnow() - timedelta(days=days)

    base = db.query(QAInteraction).filter(
        QAInteraction.knowledge_base_id == knowledge_base_id,
        QAInteraction.created_at >= since,
    )
    total_interactions = base.count()

    # by_retrieval_mode
    mode_rows = (
        db.query(QAInteraction.retrieval_mode, func.count(QAInteraction.id))
        .filter(
            QAInteraction.knowledge_base_id == knowledge_base_id,
            QAInteraction.created_at >= since,
        )
        .group_by(QAInteraction.retrieval_mode)
        .all()
    )
    by_retrieval_mode = {mode: count for mode, count in mode_rows if mode}

    # feedback joined to in-scope interactions
    feedback_q = (
        db.query(QAFeedback)
        .join(QAInteraction, QAFeedback.interaction_id == QAInteraction.id)
        .filter(
            QAInteraction.knowledge_base_id == knowledge_base_id,
            QAInteraction.created_at >= since,
        )
    )
    feedback_count = feedback_q.count()
    up_count = feedback_q.filter(QAFeedback.rating == FeedbackRating.UP).count()
    thumbs_up_rate = (up_count / feedback_count) if feedback_count else None

    error_rows = (
        db.query(QAFeedback.error_type, func.count(QAFeedback.id))
        .join(QAInteraction, QAFeedback.interaction_id == QAInteraction.id)
        .filter(
            QAInteraction.knowledge_base_id == knowledge_base_id,
            QAInteraction.created_at >= since,
            QAFeedback.error_type.isnot(None),
        )
        .group_by(QAFeedback.error_type)
        .all()
    )
    error_type_breakdown = {
        et.value: count for et, count in error_rows if et is not None
    }

    # evaluation averages over completed rows
    avg_row = (
        db.query(
            func.avg(QAEvaluation.faithfulness),
            func.avg(QAEvaluation.answer_relevance),
            func.avg(QAEvaluation.citation_accuracy),
        )
        .join(QAInteraction, QAEvaluation.interaction_id == QAInteraction.id)
        .filter(
            QAInteraction.knowledge_base_id == knowledge_base_id,
            QAInteraction.created_at >= since,
            QAEvaluation.status == EvaluationStatus.COMPLETED,
        )
        .one()
    )

    def _round(v):
        return round(float(v), 4) if v is not None else None

    return {
        "total_interactions": total_interactions,
        "feedback_count": feedback_count,
        "thumbs_up_rate": _round(thumbs_up_rate),
        "avg_faithfulness": _round(avg_row[0]),
        "avg_relevance": _round(avg_row[1]),
        "avg_citation_accuracy": _round(avg_row[2]),
        "error_type_breakdown": error_type_breakdown,
        "by_retrieval_mode": by_retrieval_mode,
    }
