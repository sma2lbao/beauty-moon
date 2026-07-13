from app.db.database import Base
from app.db.models import (
    ExperimentStatus,
    PromptExperiment,
    PromptSource,
    PromptStatus,
    PromptVersion,
    QAInteraction,
)


def test_tables_registered():
    tables = Base.metadata.tables
    assert "prompt_versions" in tables
    assert "prompt_experiments" in tables


def test_qa_interaction_has_prompt_version_id():
    assert "prompt_version_id" in QAInteraction.__table__.columns


def test_prompt_version_columns():
    cols = PromptVersion.__table__.columns
    for name in (
        "id", "prompt_key", "version_label", "lang", "template_text",
        "status", "source", "knowledge_base_id", "created_at",
    ):
        assert name in cols


def test_prompt_experiment_columns():
    cols = PromptExperiment.__table__.columns
    for name in ("id", "knowledge_base_id", "prompt_key", "status", "variants", "created_at"):
        assert name in cols


def test_enum_values():
    assert PromptStatus.ACTIVE.value == "active"
    assert PromptSource.FILE.value == "file"
    assert ExperimentStatus.RUNNING.value == "running"
