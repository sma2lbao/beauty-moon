"""Per-version aggregation + significance comparison for prompt experiments."""
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.models import (
    EvaluationStatus,
    ExperimentStatus,
    FeedbackRating,
    PromptExperiment,
    QAEvaluation,
    QAFeedback,
    QAInteraction,
)
from app.prompts.stats import two_proportion_z_test, welch_t_test

_CONTINUOUS = ("faithfulness", "answer_relevance", "citation_accuracy")


def _scores(db: Session, kb: str, version_id: str, column) -> list[float]:
    rows = (
        db.query(column)
        .join(QAInteraction, QAEvaluation.interaction_id == QAInteraction.id)
        .filter(
            QAInteraction.knowledge_base_id == kb,
            QAInteraction.prompt_version_id == version_id,
            QAEvaluation.status == EvaluationStatus.COMPLETED,
            column.isnot(None),
        )
        .all()
    )
    return [float(r[0]) for r in rows]


def _feedback_counts(db: Session, kb: str, version_id: str) -> tuple[int, int]:
    q = (
        db.query(QAFeedback)
        .join(QAInteraction, QAFeedback.interaction_id == QAInteraction.id)
        .filter(
            QAInteraction.knowledge_base_id == kb,
            QAInteraction.prompt_version_id == version_id,
        )
    )
    total = q.count()
    up = q.filter(QAFeedback.rating == FeedbackRating.UP).count()
    return up, total


def _n(db: Session, kb: str, version_id: str) -> int:
    return (
        db.query(func.count(QAInteraction.id))
        .filter(
            QAInteraction.knowledge_base_id == kb,
            QAInteraction.prompt_version_id == version_id,
        )
        .scalar()
    ) or 0


def _mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 4) if values else None


def _verdict(p_value, diff, insufficient) -> str:
    if insufficient:
        return "insufficient_sample"
    if p_value is not None and p_value < 0.05:
        return (
            "variant significantly better"
            if diff > 0
            else "variant significantly worse"
        )
    return "no significant difference"


def build_experiment_report(
    db: Session, knowledge_base_id: str, prompt_key: str
) -> dict:
    exp = (
        db.query(PromptExperiment)
        .filter(
            PromptExperiment.knowledge_base_id == knowledge_base_id,
            PromptExperiment.prompt_key == prompt_key,
            PromptExperiment.status == ExperimentStatus.RUNNING,
        )
        .first()
    )
    if exp is None or not exp.variants:
        return {"prompt_key": prompt_key, "variants": [], "comparisons": []}

    version_ids = [v["version_id"] for v in exp.variants]

    # per-variant aggregates
    agg: dict[str, dict] = {}
    variants_out = []
    for vid in version_ids:
        scores = {c: _scores(db, knowledge_base_id, vid, getattr(QAEvaluation, c)) for c in _CONTINUOUS}
        up, fb_total = _feedback_counts(db, knowledge_base_id, vid)
        agg[vid] = {"scores": scores, "up": up, "fb_total": fb_total}
        metrics = {c: {"mean": _mean(scores[c])} for c in _CONTINUOUS}
        metrics["positive_rate"] = {
            "rate": round(up / fb_total, 4) if fb_total else None
        }
        variants_out.append({"version_id": vid, "n": _n(db, knowledge_base_id, vid), "metrics": metrics})

    # comparisons: each variant vs baseline (first)
    baseline = version_ids[0]
    comparisons = []
    for vid in version_ids[1:]:
        for c in _CONTINUOUS:
            res = welch_t_test(agg[baseline]["scores"][c], agg[vid]["scores"][c])
            comparisons.append({
                "baseline": baseline, "variant": vid, "metric": c, "test": "welch_t",
                "p_value": res.p_value, "diff": res.diff, "ci95": list(res.ci95) if res.ci95 else None,
                "verdict": _verdict(res.p_value, res.diff, res.insufficient),
            })
        z = two_proportion_z_test(
            agg[baseline]["up"], agg[baseline]["fb_total"],
            agg[vid]["up"], agg[vid]["fb_total"],
        )
        comparisons.append({
            "baseline": baseline, "variant": vid, "metric": "positive_rate",
            "test": "two_proportion_z", "p_value": z.p_value, "diff": z.diff,
            "ci95": list(z.ci95) if z.ci95 else None,
            "verdict": _verdict(z.p_value, z.diff, z.insufficient),
        })

    return {"prompt_key": prompt_key, "variants": variants_out, "comparisons": comparisons}
