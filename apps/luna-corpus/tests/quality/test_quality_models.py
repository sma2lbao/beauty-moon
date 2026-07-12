"""Unit tests for quality evaluation models."""
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


def _session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def test_interaction_persists_sources_json():
    session = _session()
    interaction = QAInteraction(
        knowledge_base_id="kb-1",
        question="Q?",
        answer="A.",
        sources=[{"document_id": "d1", "chunk_content": "c", "relevance_score": 0.9}],
        retrieval_mode="hybrid",
        processing_time_ms=120,
    )
    session.add(interaction)
    session.commit()
    row = session.query(QAInteraction).one()
    assert row.id
    assert row.sources[0]["document_id"] == "d1"
    assert row.created_at is not None


def test_feedback_and_evaluation_link_to_interaction():
    session = _session()
    interaction = QAInteraction(
        knowledge_base_id="kb-1", question="Q", answer="A", sources=[]
    )
    session.add(interaction)
    session.commit()

    feedback = QAFeedback(
        interaction_id=interaction.id,
        rating=FeedbackRating.DOWN,
        error_type=FeedbackErrorType.HALLUCINATION,
        comment="wrong",
    )
    evaluation = QAEvaluation(
        interaction_id=interaction.id,
        status=EvaluationStatus.PENDING,
    )
    session.add_all([feedback, evaluation])
    session.commit()

    assert session.query(QAFeedback).one().rating == FeedbackRating.DOWN
    assert session.query(QAEvaluation).one().status == EvaluationStatus.PENDING
