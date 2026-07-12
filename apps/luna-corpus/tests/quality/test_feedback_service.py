"""Unit tests for feedback service."""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models import Base, FeedbackErrorType, FeedbackRating, QAInteraction
from app.quality.feedback import create_feedback, get_interaction


def _session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def _interaction(session, kb="kb-1"):
    inter = QAInteraction(
        knowledge_base_id=kb, question="Q", answer="A", sources=[]
    )
    session.add(inter)
    session.commit()
    return inter.id


def test_get_interaction_scoped_by_kb():
    session = _session()
    iid = _interaction(session, kb="kb-1")
    assert get_interaction(session, iid, "kb-1") is not None
    assert get_interaction(session, iid, "kb-other") is None


def test_create_feedback_persists():
    session = _session()
    iid = _interaction(session)
    fb = create_feedback(
        session,
        interaction_id=iid,
        rating=FeedbackRating.DOWN,
        error_type=FeedbackErrorType.HALLUCINATION,
        comment="bad",
        created_by_user_id="u1",
    )
    assert fb.id is not None
    assert fb.rating == FeedbackRating.DOWN
    assert fb.error_type == FeedbackErrorType.HALLUCINATION
