"""Unit tests for interaction recorder and sampling."""
from unittest.mock import MagicMock

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models import Base, QAInteraction
from app.quality.recorder import record_interaction, should_evaluate


def _session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def test_record_interaction_persists_and_returns_id():
    session = _session()
    interaction_id = record_interaction(
        session,
        knowledge_base_id="kb-1",
        question="Q?",
        answer="A.",
        sources=[{"document_id": "d1", "chunk_content": "c", "relevance_score": 0.9}],
        retrieval_mode="hybrid",
        processing_time_ms=100,
    )
    assert interaction_id is not None
    assert session.query(QAInteraction).count() == 1


def test_record_interaction_swallows_errors():
    broken = MagicMock()
    broken.add.side_effect = RuntimeError("db down")
    # 不应抛出，返回 None
    assert record_interaction(
        broken, knowledge_base_id="kb", question="Q", answer="A", sources=[]
    ) is None


def test_should_evaluate_bounds(monkeypatch):
    from app.quality import recorder

    monkeypatch.setattr(recorder.settings, "quality_eval_sample_rate", 0.0)
    assert should_evaluate(rand=0.0) is False
    monkeypatch.setattr(recorder.settings, "quality_eval_sample_rate", 1.0)
    assert should_evaluate(rand=0.999) is True
    monkeypatch.setattr(recorder.settings, "quality_eval_sample_rate", 0.5)
    assert should_evaluate(rand=0.4) is True
    assert should_evaluate(rand=0.6) is False


def test_record_interaction_persists_prompt_version_id(db_session):
    from app.db.models import QAInteraction
    from app.quality.recorder import record_interaction

    iid = record_interaction(
        db_session,
        knowledge_base_id="kb-1",
        question="q",
        answer="a",
        sources=[],
        prompt_version_id="ver-123",
    )
    assert iid is not None
    row = db_session.query(QAInteraction).filter(QAInteraction.id == iid).first()
    assert row.prompt_version_id == "ver-123"
