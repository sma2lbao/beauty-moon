"""Unit tests for quality aggregation."""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models import (
    Base,
    EvaluationStatus,
    FeedbackErrorType,
    FeedbackRating,
    QAEvaluation,
    QAFeedback,
    QAInteraction,
)
from app.quality.aggregation import summarize_quality


def _session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def test_summary_empty_returns_zeros():
    session = _session()
    summary = summarize_quality(session, "kb-1")
    assert summary["total_interactions"] == 0
    assert summary["feedback_count"] == 0
    assert summary["thumbs_up_rate"] is None
    assert summary["avg_faithfulness"] is None
    assert summary["error_type_breakdown"] == {}


def test_summary_aggregates():
    session = _session()
    inter = QAInteraction(
        knowledge_base_id="kb-1",
        question="Q",
        answer="A",
        sources=[],
        retrieval_mode="hybrid",
    )
    session.add(inter)
    session.commit()

    session.add_all([
        QAFeedback(interaction_id=inter.id, rating=FeedbackRating.UP),
        QAFeedback(
            interaction_id=inter.id,
            rating=FeedbackRating.DOWN,
            error_type=FeedbackErrorType.HALLUCINATION,
        ),
        QAEvaluation(
            interaction_id=inter.id,
            faithfulness=0.8,
            answer_relevance=0.6,
            citation_accuracy=1.0,
            status=EvaluationStatus.COMPLETED,
        ),
    ])
    session.commit()

    summary = summarize_quality(session, "kb-1")
    assert summary["total_interactions"] == 1
    assert summary["feedback_count"] == 2
    assert summary["thumbs_up_rate"] == 0.5
    assert summary["avg_faithfulness"] == 0.8
    assert summary["error_type_breakdown"]["hallucination"] == 1
    assert summary["by_retrieval_mode"]["hybrid"] == 1
