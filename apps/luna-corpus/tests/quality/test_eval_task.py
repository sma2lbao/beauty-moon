"""Async evaluation task: completed and failed paths."""
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models import (
    Base,
    EvaluationStatus,
    QAEvaluation,
    QAInteraction,
)
from app.quality import tasks as tasks_module
from app.quality.judge import QualityJudge, QualityScores


class _FakeJudge(QualityJudge):
    def __init__(self, scores=None, error=None):
        self._scores = scores
        self._error = error

    def evaluate(self, question, answer, sources):
        if self._error:
            raise self._error
        return self._scores


def _setup(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    # 让任务内部的 SessionLocal() 复用本引擎
    monkeypatch.setattr(tasks_module, "SessionLocal", Session)
    return Session


def _interaction(session):
    inter = QAInteraction(
        knowledge_base_id="kb", question="Q", answer="A", sources=[]
    )
    session.add(inter)
    session.commit()
    return inter.id


def test_eval_task_completed(monkeypatch):
    Session = _setup(monkeypatch)
    session = Session()
    interaction_id = _interaction(session)
    eval_id = tasks_module.create_pending_evaluation(session, interaction_id)

    judge = _FakeJudge(
        scores=QualityScores(0.9, 0.8, 0.7, rationale="ok", model="fake")
    )
    tasks_module._run_eval_task(eval_id, judge=judge)

    row = session.get(QAEvaluation, eval_id)
    session.refresh(row)
    assert row.status == EvaluationStatus.COMPLETED
    assert row.faithfulness == 0.9
    assert row.judge_model == "fake"


def test_eval_task_failed(monkeypatch):
    Session = _setup(monkeypatch)
    session = Session()
    interaction_id = _interaction(session)
    eval_id = tasks_module.create_pending_evaluation(session, interaction_id)

    judge = _FakeJudge(error=RuntimeError("llm down"))
    tasks_module._run_eval_task(eval_id, judge=judge)

    row = session.get(QAEvaluation, eval_id)
    session.refresh(row)
    assert row.status == EvaluationStatus.FAILED
