import pytest
from unittest import mock

from app.db.models import (
    ExperimentStatus,
    PromptExperiment,
    PromptSource,
    PromptStatus,
    PromptVersion,
)
from app.prompts import experiment, registry
from app.prompts.defaults import default_version_id


@pytest.fixture(autouse=True)
def _clear_cache():
    registry.invalidate_all()
    yield
    registry.invalidate_all()


def test_stable_bucket_is_deterministic():
    b1 = experiment.stable_bucket("conv-123", "rag_qa")
    b2 = experiment.stable_bucket("conv-123", "rag_qa")
    assert b1 == b2
    assert 0 <= b1 < 100


def test_stable_bucket_varies_by_seed():
    """200 different seeds should produce >= 80 unique buckets (0..99 range)."""
    buckets = {experiment.stable_bucket(f"conv-{i}", "rag_qa") for i in range(200)}
    assert len(buckets) >= 80, f"expected >=80 unique buckets, got {len(buckets)}"


def test_pick_version_boundaries():
    variants = [{"version_id": "A", "weight": 50}, {"version_id": "B", "weight": 50}]
    assert experiment.pick_version_id(variants, 0) == "A"
    assert experiment.pick_version_id(variants, 49) == "A"
    assert experiment.pick_version_id(variants, 50) == "B"
    assert experiment.pick_version_id(variants, 99) == "B"


def test_pick_version_empty_returns_none():
    assert experiment.pick_version_id([], 10) is None
    assert experiment.pick_version_id([{"version_id": "A", "weight": 0}], 10) is None


def test_select_version_no_experiment_returns_default(db_session):
    t = experiment.select_version(db_session, "kb-1", "rag_qa", "zh", seed="s1")
    assert t.version_id == default_version_id("rag_qa", "zh")


def test_select_version_running_experiment_picks_variant(db_session):
    row = PromptVersion(
        prompt_key="rag_qa", version_label="v2", lang="zh",
        template_text="变体 {body}", status=PromptStatus.ACTIVE, source=PromptSource.DB,
    )
    db_session.add(row)
    db_session.commit()
    exp = PromptExperiment(
        knowledge_base_id="kb-1", prompt_key="rag_qa",
        status=ExperimentStatus.RUNNING,
        variants=[{"version_id": row.id, "weight": 100}],
    )
    db_session.add(exp)
    db_session.commit()
    t = experiment.select_version(db_session, "kb-1", "rag_qa", "zh", seed="s1")
    assert t.version_id == row.id


def test_select_version_stopped_experiment_ignored(db_session):
    exp = PromptExperiment(
        knowledge_base_id="kb-9", prompt_key="rag_qa",
        status=ExperimentStatus.STOPPED,
        variants=[{"version_id": "whatever", "weight": 100}],
    )
    db_session.add(exp)
    db_session.commit()
    t = experiment.select_version(db_session, "kb-9", "rag_qa", "zh", seed="s1")
    assert t.version_id == default_version_id("rag_qa", "zh")


# ---- pick_version_id non-uniform / multi-variant / non-100 total ----


def test_pick_version_nonuniform_30_70():
    """Non-uniform 30/70 split: bucket 0..29 → A, 30..99 → B."""
    variants = [
        {"version_id": "A", "weight": 30},
        {"version_id": "B", "weight": 70},
    ]
    # hand-calc: threshold = bucket * 100 / 100 = bucket
    # bucket < 30 → A, bucket >= 30 → B
    assert experiment.pick_version_id(variants, 0) == "A"
    assert experiment.pick_version_id(variants, 29) == "A"
    assert experiment.pick_version_id(variants, 30) == "B"
    assert experiment.pick_version_id(variants, 99) == "B"


def test_pick_version_three_variants_33_33_34():
    """Three variants 33/33/34: verify bucket→variant mapping at boundaries."""
    variants = [
        {"version_id": "A", "weight": 33},
        {"version_id": "B", "weight": 33},
        {"version_id": "C", "weight": 34},
    ]
    # hand-calc: threshold = bucket * 100 / 100 = bucket
    # bucket 0..32 (<33) → A, 33..65 (<66) → B, 66..99 → C
    assert experiment.pick_version_id(variants, 0) == "A"
    assert experiment.pick_version_id(variants, 32) == "A"
    assert experiment.pick_version_id(variants, 33) == "B"
    assert experiment.pick_version_id(variants, 65) == "B"
    assert experiment.pick_version_id(variants, 66) == "C"
    assert experiment.pick_version_id(variants, 99) == "C"


def test_pick_version_weights_sum_not_100():
    """Weights sum to 10 (3/7): verify scaling logic, bucket 0..29 → A, 30..99 → B."""
    variants = [
        {"version_id": "A", "weight": 3},
        {"version_id": "B", "weight": 7},
    ]
    # hand-calc: threshold = bucket * 10 / 100
    # bucket 0:  threshold=0.0,  cum after A=3,  0.0 < 3  → A
    # bucket 29: threshold=2.9,  cum after A=3,  2.9 < 3  → A
    # bucket 30: threshold=3.0,  cum after A=3,  3.0 >= 3 → B, cum after B=10, 3.0 < 10 → B
    # bucket 99: threshold=9.9,  cum after A=3,  9.9 >= 3 → B, cum after B=10, 9.9 < 10 → B
    assert experiment.pick_version_id(variants, 0) == "A"
    assert experiment.pick_version_id(variants, 29) == "A"
    assert experiment.pick_version_id(variants, 30) == "B"
    assert experiment.pick_version_id(variants, 99) == "B"


# ---- select_version exception path ----


def test_select_version_falls_back_on_registry_error(db_session):
    """When registry.get_template_by_version_id raises, fall back to file default."""
    row = PromptVersion(
        prompt_key="rag_qa", version_label="v2", lang="zh",
        template_text="变体 {body}", status=PromptStatus.ACTIVE, source=PromptSource.DB,
    )
    db_session.add(row)
    db_session.commit()
    exp = PromptExperiment(
        knowledge_base_id="kb-1", prompt_key="rag_qa",
        status=ExperimentStatus.RUNNING,
        variants=[{"version_id": row.id, "weight": 100}],
    )
    db_session.add(exp)
    db_session.commit()

    with mock.patch.object(
        experiment.registry, "get_template_by_version_id",
        side_effect=RuntimeError("simulated registry error"),
    ):
        t = experiment.select_version(db_session, "kb-1", "rag_qa", "zh", seed="s1")
        assert t.version_id == default_version_id("rag_qa", "zh")
