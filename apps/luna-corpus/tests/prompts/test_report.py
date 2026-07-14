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


def _seed_interactions(
    db, kb, version_id, n, faith, up_count,
    status=EvaluationStatus.COMPLETED, jitter=0.0,
):
    for i in range(n):
        it = QAInteraction(
            knowledge_base_id=kb, question="q", answer="a", sources=[],
            prompt_version_id=version_id,
        )
        db.add(it)
        db.flush()
        # jitter alternates +/- so the sample has non-zero variance but a
        # stable mean == faith; lets us exercise the real t-test branches.
        val = faith + (jitter if i % 2 == 0 else -jitter)
        db.add(QAEvaluation(
            interaction_id=it.id, faithfulness=val, answer_relevance=val,
            citation_accuracy=val, status=status,
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
    # positive_rate: A=12/40=0.3, B=32/40=0.8 → significantly better
    pos_cmp = next(
        c for c in rep["comparisons"]
        if c["variant"] == "B" and c["metric"] == "positive_rate"
    )
    assert pos_cmp["test"] == "two_proportion_z"
    assert pos_cmp["diff"] > 0
    assert pos_cmp["p_value"] < 0.05
    assert pos_cmp["verdict"] == "variant significantly better"
    b = next(v for v in rep["variants"] if v["version_id"] == "B")
    assert b["metrics"]["positive_rate"]["rate"] == 0.8


def test_report_no_significant_difference(db_session):
    """Equal means (diff == 0) → real t-test path yields no significance."""
    exp = PromptExperiment(
        knowledge_base_id="kb-eq", prompt_key="rag_qa",
        status=ExperimentStatus.RUNNING,
        variants=[{"version_id": "A", "weight": 50}, {"version_id": "B", "weight": 50}],
    )
    db_session.add(exp)
    db_session.commit()
    # identical mean + identical up_count → diff == 0 for both metrics
    _seed_interactions(db_session, "kb-eq", "A", n=40, faith=0.6, up_count=20, jitter=0.05)
    _seed_interactions(db_session, "kb-eq", "B", n=40, faith=0.6, up_count=20, jitter=0.05)

    rep = build_experiment_report(db_session, "kb-eq", "rag_qa")
    faith_cmp = next(
        c for c in rep["comparisons"]
        if c["variant"] == "B" and c["metric"] == "faithfulness"
    )
    assert faith_cmp["p_value"] is not None
    assert faith_cmp["verdict"] == "no significant difference"
    pos_cmp = next(
        c for c in rep["comparisons"]
        if c["variant"] == "B" and c["metric"] == "positive_rate"
    )
    assert pos_cmp["diff"] == 0
    assert pos_cmp["verdict"] == "no significant difference"


def test_report_variant_significantly_worse(db_session):
    """Baseline A better than variant B (diff < 0) → significantly worse."""
    exp = PromptExperiment(
        knowledge_base_id="kb-w", prompt_key="rag_qa",
        status=ExperimentStatus.RUNNING,
        variants=[{"version_id": "A", "weight": 50}, {"version_id": "B", "weight": 50}],
    )
    db_session.add(exp)
    db_session.commit()
    _seed_interactions(db_session, "kb-w", "A", n=40, faith=0.9, up_count=36, jitter=0.02)
    _seed_interactions(db_session, "kb-w", "B", n=40, faith=0.4, up_count=8, jitter=0.02)

    rep = build_experiment_report(db_session, "kb-w", "rag_qa")
    faith_cmp = next(
        c for c in rep["comparisons"]
        if c["variant"] == "B" and c["metric"] == "faithfulness"
    )
    assert faith_cmp["diff"] < 0
    assert faith_cmp["p_value"] < 0.05
    assert faith_cmp["verdict"] == "variant significantly worse"
    pos_cmp = next(
        c for c in rep["comparisons"]
        if c["variant"] == "B" and c["metric"] == "positive_rate"
    )
    assert pos_cmp["verdict"] == "variant significantly worse"


def test_report_isolates_by_knowledge_base(db_session):
    """Interactions in another KB must not leak into this KB's report."""
    exp = PromptExperiment(
        knowledge_base_id="kb-main", prompt_key="rag_qa",
        status=ExperimentStatus.RUNNING,
        variants=[{"version_id": "A", "weight": 50}, {"version_id": "B", "weight": 50}],
    )
    db_session.add(exp)
    db_session.commit()
    _seed_interactions(db_session, "kb-main", "A", n=40, faith=0.5, up_count=20, jitter=0.05)
    _seed_interactions(db_session, "kb-main", "B", n=40, faith=0.5, up_count=20, jitter=0.05)
    # noise in a different KB using the same version ids
    _seed_interactions(db_session, "kb-other", "A", n=40, faith=0.99, up_count=40)
    _seed_interactions(db_session, "kb-other", "B", n=40, faith=0.01, up_count=0)

    rep = build_experiment_report(db_session, "kb-main", "rag_qa")
    a = next(v for v in rep["variants"] if v["version_id"] == "A")
    assert a["n"] == 40  # not 80 — other KB excluded
    assert a["metrics"]["faithfulness"]["mean"] == 0.5


def test_report_excludes_non_completed_evaluations(db_session):
    """Only COMPLETED evaluations feed the continuous metrics."""
    exp = PromptExperiment(
        knowledge_base_id="kb-p", prompt_key="rag_qa",
        status=ExperimentStatus.RUNNING,
        variants=[{"version_id": "A", "weight": 50}, {"version_id": "B", "weight": 50}],
    )
    db_session.add(exp)
    db_session.commit()
    _seed_interactions(db_session, "kb-p", "A", n=40, faith=0.5, up_count=20, jitter=0.05)
    # B's evaluations are all PENDING → excluded from t-test → insufficient
    _seed_interactions(
        db_session, "kb-p", "B", n=40, faith=0.8, up_count=32,
        status=EvaluationStatus.PENDING, jitter=0.05,
    )

    rep = build_experiment_report(db_session, "kb-p", "rag_qa")
    b = next(v for v in rep["variants"] if v["version_id"] == "B")
    assert b["metrics"]["faithfulness"]["mean"] is None  # no COMPLETED scores
    # feedback is independent of evaluation status → positive_rate still computed
    assert b["metrics"]["positive_rate"]["rate"] == 0.8
    faith_cmp = next(
        c for c in rep["comparisons"]
        if c["variant"] == "B" and c["metric"] == "faithfulness"
    )
    assert faith_cmp["verdict"] == "insufficient_sample"


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
