import pytest

from app.db.models import PromptSource, PromptStatus, PromptVersion
from app.prompts import registry
from app.prompts.defaults import default_version_id


@pytest.fixture(autouse=True)
def _clear_cache():
    registry.invalidate_all()
    yield
    registry.invalidate_all()


def test_get_default_template_zh():
    t = registry.get_default_template("rag_qa", "zh")
    assert t.version_id == default_version_id("rag_qa", "zh")
    assert "{body}" in t.template_text
    assert t.lang == "zh"


def test_unknown_lang_falls_back_to_zh():
    t = registry.get_default_template("rag_qa", "fr")
    assert t.lang == "zh"


def test_file_version_id_returns_default(db_session):
    t = registry.get_template_by_version_id(
        db_session, default_version_id("rag_qa", "en"), "rag_qa", "en"
    )
    assert t.lang == "en"
    assert "{body}" in t.template_text


def test_db_version_id_reads_row(db_session):
    row = PromptVersion(
        prompt_key="rag_qa",
        version_label="v2-concise",
        lang="zh",
        template_text="自定义 {body} 模板",
        status=PromptStatus.ACTIVE,
        source=PromptSource.DB,
    )
    db_session.add(row)
    db_session.commit()
    t = registry.get_template_by_version_id(db_session, row.id, "rag_qa", "zh")
    assert t.version_id == row.id
    assert t.version_label == "v2-concise"
    assert "自定义" in t.template_text


def test_missing_db_row_falls_back_to_default(db_session):
    t = registry.get_template_by_version_id(
        db_session, "00000000-0000-0000-0000-000000000000", "rag_qa", "zh"
    )
    assert t.version_id == default_version_id("rag_qa", "zh")