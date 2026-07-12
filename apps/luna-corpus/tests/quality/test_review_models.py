"""Unit tests for the qa_reviews model."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models import (
    Base,
    QAInteraction,
    QAReview,
    ReviewRootCause,
    ReviewStatus,
)


def _session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def _interaction(session):
    interaction = QAInteraction(
        knowledge_base_id="kb-1", question="Q", answer="A", sources=[]
    )
    session.add(interaction)
    session.commit()
    return interaction


def test_review_defaults_to_open():
    session = _session()
    interaction = _interaction(session)
    review = QAReview(interaction_id=interaction.id)
    session.add(review)
    session.commit()
    row = session.query(QAReview).one()
    assert row.id
    assert row.status == ReviewStatus.OPEN
    assert row.root_cause is None
    assert row.created_at is not None


def test_review_stores_resolution_fields():
    session = _session()
    interaction = _interaction(session)
    review = QAReview(
        interaction_id=interaction.id,
        status=ReviewStatus.RESOLVED,
        root_cause=ReviewRootCause.KNOWLEDGE_GAP,
        resolution_note="补充了缺失文档",
        resolved_by_user_id="user-9",
    )
    session.add(review)
    session.commit()
    row = session.query(QAReview).one()
    assert row.status == ReviewStatus.RESOLVED
    assert row.root_cause == ReviewRootCause.KNOWLEDGE_GAP
    assert row.resolution_note == "补充了缺失文档"


def test_one_review_per_interaction():
    session = _session()
    interaction = _interaction(session)
    session.add(QAReview(interaction_id=interaction.id))
    session.commit()
    session.add(QAReview(interaction_id=interaction.id))
    with pytest.raises(IntegrityError):
        session.commit()
