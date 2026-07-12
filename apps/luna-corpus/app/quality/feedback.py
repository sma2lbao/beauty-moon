"""Feedback service: KB-scoped lookup and feedback creation."""
from sqlalchemy.orm import Session

from app.db.models import (
    FeedbackErrorType,
    FeedbackRating,
    QAFeedback,
    QAInteraction,
)
from app.observability.metrics import QA_FEEDBACK_TOTAL


def get_interaction(
    db: Session, interaction_id: str, knowledge_base_id: str
) -> QAInteraction | None:
    """Return the interaction only if it belongs to the given knowledge base."""
    return (
        db.query(QAInteraction)
        .filter(
            QAInteraction.id == interaction_id,
            QAInteraction.knowledge_base_id == knowledge_base_id,
        )
        .first()
    )


def create_feedback(
    db: Session,
    *,
    interaction_id: str,
    rating: FeedbackRating,
    error_type: FeedbackErrorType | None = None,
    comment: str | None = None,
    created_by_user_id: str | None = None,
) -> QAFeedback:
    """Persist a feedback row (caller commits)."""
    feedback = QAFeedback(
        interaction_id=interaction_id,
        rating=rating,
        error_type=error_type,
        comment=comment,
        created_by_user_id=created_by_user_id,
    )
    db.add(feedback)
    db.flush()
    QA_FEEDBACK_TOTAL.labels(rating=rating.value).inc()
    return feedback
