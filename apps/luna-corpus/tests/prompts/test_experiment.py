import pytest

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
    buckets = {experiment.stable_bucket(f"conv-{i}", "rag_qa") for i in range(50)}
    assert len(buckets) > 1  # not all identical


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
