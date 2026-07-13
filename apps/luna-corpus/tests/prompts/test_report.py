import pytest

from app.db.models import (
    EvaluationStatus,
    ExperimentStatus,
    FeedbackRating,
    PromptExperiment,
    QAEvaluation,
    QAFeedback,
    QAInteraction,
)
from app.prompts.report import build_experiment_report


def _seed_interactions(db, kb, version_id, n, faith, up_count):
    for i in range(n):
        it = QAInteraction(
            knowledge_base_id=kb, question="q", answer="a", sources=[],
            prompt_version_id=version_id,
        )
        db.add(it)
        db.flush()
        db.add(QAEvaluation(
            interaction_id=it.id, faithfulness=faith, answer_relevance=faith,
            citation_accuracy=faith, status=EvaluationStatus.COMPLETED,
        ))
        rating = FeedbackRating.UP if i < up_count else FeedbackRating.DOWN
        db.add(QAFeedback(interaction_id=it.id, rating=rating))
    db.commit()


def test_report_no_experiment_empty(db_session):
    rep = build_experiment_report(db_session, "kb-x", "rag_qa")
    assert rep["variants"] == []
    assert rep["comparisons"] == []


def test_report_two_variants_with_comparison(db_session):
    exp = PromptExperiment(
        knowledge_base_id="kb-1", prompt_key="rag_qa",
        status=ExperimentStatus.RUNNING,
        variants=[{"version_id": "A", "weight": 50}, {"version_id": "B", "weight": 50}],
    )
    db_session.add(exp)
    db_session.commit()
    _seed_interactions(db_session, "kb-1", "A", n=40, faith=0.5, up_count=12)
    _seed_interactions(db_session, "kb-1", "B", n=40, faith=0.8, up_count=32)

    rep = build_experiment_report(db_session, "kb-1", "rag_qa")
    labels = {v["version_id"] for v in rep["variants"]}
    assert labels == {"A", "B"}
    a = next(v for v in rep["variants"] if v["version_id"] == "A")
    assert a["n"] == 40
    faith_cmp = next(
        c for c in rep["comparisons"]
        if c["variant"] == "B" and c["metric"] == "faithfulness"
    )
    assert faith_cmp["baseline"] == "A"
    assert faith_cmp["p_value"] < 0.05
    assert faith_cmp["verdict"] == "variant significantly better"


def test_report_small_sample_insufficient(db_session):
    exp = PromptExperiment(
        knowledge_base_id="kb-2", prompt_key="rag_qa",
        status=ExperimentStatus.RUNNING,
        variants=[{"version_id": "A", "weight": 50}, {"version_id": "B", "weight": 50}],
    )
    db_session.add(exp)
    db_session.commit()
    _seed_interactions(db_session, "kb-2", "A", n=5, faith=0.5, up_count=2)
    _seed_interactions(db_session, "kb-2", "B", n=5, faith=0.8, up_count=4)

    rep = build_experiment_report(db_session, "kb-2", "rag_qa")
    faith_cmp = next(
        c for c in rep["comparisons"]
        if c["variant"] == "B" and c["metric"] == "faithfulness"
    )
    assert faith_cmp["verdict"] == "insufficient_sample"
    assert faith_cmp["p_value"] is None