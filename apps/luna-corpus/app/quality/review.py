"""Review derivation and triage service for the feedback loop.

The review queue is DERIVED at query time (no materialized queue table):
an interaction is queued when it has a thumbs-down feedback OR a completed
low-score evaluation, and has no terminal (resolved/dismissed) review.
Triage state lives in the qa_reviews table, upserted one row per interaction.
"""
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import (
    EvaluationStatus,
    FeedbackRating,
    QAEvaluation,
    QAFeedback,
    QAInteraction,
    QAReview,
    ReviewRootCause,
    ReviewStatus,
)

settings = get_settings()

_TERMINAL = (ReviewStatus.RESOLVED, ReviewStatus.DISMISSED)


def _has_thumbs_down(db: Session, interaction_id: str) -> bool:
    return (
        db.query(QAFeedback)
        .filter(
            QAFeedback.interaction_id == interaction_id,
            QAFeedback.rating == FeedbackRating.DOWN,
        )
        .first()
        is not None
    )


def _has_low_score(db: Session, interaction_id: str) -> bool:
    threshold = settings.quality_review_score_threshold
    return (
        db.query(QAEvaluation)
        .filter(
            QAEvaluation.interaction_id == interaction_id,
            QAEvaluation.status == EvaluationStatus.COMPLETED,
            (QAEvaluation.faithfulness < threshold)
            | (QAEvaluation.answer_relevance < threshold),
        )
        .first()
        is not None
    )


def _get_scoped_interaction(
    db: Session, kb_id: str, interaction_id: str
) -> QAInteraction | None:
    return (
        db.query(QAInteraction)
        .filter(
            QAInteraction.id == interaction_id,
            QAInteraction.knowledge_base_id == kb_id,
        )
        .first()
    )


def _get_review(db: Session, interaction_id: str) -> QAReview | None:
    return (
        db.query(QAReview)
        .filter(QAReview.interaction_id == interaction_id)
        .first()
    )


def list_reviews(
    db: Session,
    kb_id: str,
    *,
    status_filter: str = "queue",
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    """Derive the review list for a KB.

    status_filter="queue": interactions triggering a signal with no terminal
    review. "resolved"/"dismissed": interactions whose review is in that state.
    """
    interactions = (
        db.query(QAInteraction)
        .filter(QAInteraction.knowledge_base_id == kb_id)
        .order_by(QAInteraction.created_at.desc())
        .all()
    )
    rows: list[dict] = []
    for it in interactions:
        review = _get_review(db, it.id)
        thumbs_down = _has_thumbs_down(db, it.id)
        low_score = _has_low_score(db, it.id)
        triggered = thumbs_down or low_score

        if status_filter == "queue":
            in_terminal = review is not None and review.status in _TERMINAL
            if not triggered or in_terminal:
                continue
        else:  # "resolved" / "dismissed"
            if review is None or review.status.value != status_filter:
                continue

        rows.append(
            {
                "interaction_id": it.id,
                "question": it.question,
                "answer": it.answer,
                "retrieval_mode": it.retrieval_mode,
                "created_at": it.created_at.isoformat() if it.created_at else None,
                "signals": {"thumbs_down": thumbs_down, "low_score": low_score},
                "review_status": review.status.value if review else None,
            }
        )
    return rows[offset : offset + limit]


def _feedback_dicts(db: Session, interaction_id: str) -> list[dict]:
    items = (
        db.query(QAFeedback)
        .filter(QAFeedback.interaction_id == interaction_id)
        .all()
    )
    return [
        {
            "id": f.id,
            "rating": f.rating.value,
            "error_type": f.error_type.value if f.error_type else None,
            "comment": f.comment,
        }
        for f in items
    ]


def _evaluation_dict(db: Session, interaction_id: str) -> dict | None:
    ev = (
        db.query(QAEvaluation)
        .filter(QAEvaluation.interaction_id == interaction_id)
        .order_by(QAEvaluation.created_at.desc())
        .first()
    )
    if ev is None:
        return None
    return {
        "faithfulness": ev.faithfulness,
        "answer_relevance": ev.answer_relevance,
        "citation_accuracy": ev.citation_accuracy,
        "status": ev.status.value,
        "rationale": ev.rationale,
    }


def _review_dict(review: QAReview | None) -> dict | None:
    if review is None:
        return None
    return {
        "id": review.id,
        "status": review.status.value,
        "root_cause": review.root_cause.value if review.root_cause else None,
        "resolution_note": review.resolution_note,
        "resolved_by_user_id": review.resolved_by_user_id,
    }


def get_review_detail(
    db: Session, kb_id: str, interaction_id: str
) -> dict | None:
    """Full triage detail for one interaction; None if not in this KB."""
    it = _get_scoped_interaction(db, kb_id, interaction_id)
    if it is None:
        return None
    return {
        "interaction": {
            "id": it.id,
            "question": it.question,
            "answer": it.answer,
            "sources": it.sources,
            "retrieval_mode": it.retrieval_mode,
            "created_at": it.created_at.isoformat() if it.created_at else None,
        },
        "feedback": _feedback_dicts(db, interaction_id),
        "evaluation": _evaluation_dict(db, interaction_id),
        "review": _review_dict(_get_review(db, interaction_id)),
    }


def _upsert(
    db: Session,
    kb_id: str,
    interaction_id: str,
    *,
    status: ReviewStatus,
    root_cause: ReviewRootCause | None,
    note: str | None,
    user_id: str | None,
) -> QAReview | None:
    if _get_scoped_interaction(db, kb_id, interaction_id) is None:
        return None
    review = _get_review(db, interaction_id)
    if review is None:
        review = QAReview(interaction_id=interaction_id)
        db.add(review)
    review.status = status
    review.root_cause = root_cause
    review.resolution_note = note
    review.resolved_by_user_id = user_id
    db.flush()
    return review


def resolve_review(
    db: Session,
    kb_id: str,
    interaction_id: str,
    *,
    root_cause: ReviewRootCause,
    note: str | None,
    user_id: str | None,
) -> QAReview | None:
    """Mark an interaction resolved with a root cause (upsert)."""
    return _upsert(
        db, kb_id, interaction_id,
        status=ReviewStatus.RESOLVED,
        root_cause=root_cause, note=note, user_id=user_id,
    )


def dismiss_review(
    db: Session,
    kb_id: str,
    interaction_id: str,
    *,
    note: str | None,
    user_id: str | None,
) -> QAReview | None:
    """Dismiss an interaction as not actionable (upsert)."""
    return _upsert(
        db, kb_id, interaction_id,
        status=ReviewStatus.DISMISSED,
        root_cause=None, note=note, user_id=user_id,
    )
