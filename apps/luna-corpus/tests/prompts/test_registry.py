import pytest
from unittest.mock import MagicMock

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
    assert t.prompt_key == "rag_qa"


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


# I1: fail-safe DB exception test
def test_db_exception_returns_default():
    mock_db = MagicMock()
    mock_db.query.side_effect = Exception("boom")
    t = registry.get_template_by_version_id(mock_db, "some-uuid", "rag_qa", "zh")
    assert t.version_id == default_version_id("rag_qa", "zh")
    assert "{body}" in t.template_text


# I2: empty version_id test
def test_empty_version_id_returns_default(db_session):
    t = registry.get_template_by_version_id(db_session, "", "rag_qa", "zh")
    assert t.version_id == default_version_id("rag_qa", "zh")
    assert "{body}" in t.template_text


# I3: cache hit and invalidate
def test_cache_hit_and_invalidate(db_session):
    row = PromptVersion(
        prompt_key="rag_qa",
        version_label="v2-cache-test",
        lang="zh",
        template_text="缓存测试 {body} 模板",
        status=PromptStatus.ACTIVE,
        source=PromptSource.DB,
    )
    db_session.add(row)
    db_session.commit()

    # Populate cache
    t1 = registry.get_template_by_version_id(db_session, row.id, "rag_qa", "zh")
    assert t1.version_id == row.id
    assert "缓存测试" in t1.template_text

    # Delete the row from DB
    db_session.delete(row)
    db_session.commit()

    # Cache hit: should still return the cached value
    t2 = registry.get_template_by_version_id(db_session, row.id, "rag_qa", "zh")
    assert t2.version_id == row.id
    assert "缓存测试" in t2.template_text

    # Invalidate the specific entry
    registry.invalidate(row.id)

    # After invalidation, DB has no row, should fall back to file default
    t3 = registry.get_template_by_version_id(db_session, row.id, "rag_qa", "zh")
    assert t3.version_id == default_version_id("rag_qa", "zh")


# I3: cache invalidate_all
def test_cache_invalidate_all(db_session):
    row = PromptVersion(
        prompt_key="rag_qa",
        version_label="v2-invalidate-all-test",
        lang="zh",
        template_text="全部失效测试 {body} 模板",
        status=PromptStatus.ACTIVE,
        source=PromptSource.DB,
    )
    db_session.add(row)
    db_session.commit()

    # Populate cache
    t1 = registry.get_template_by_version_id(db_session, row.id, "rag_qa", "zh")
    assert t1.version_id == row.id
    assert "全部失效测试" in t1.template_text

    # Delete from DB
    db_session.delete(row)
    db_session.commit()

    # Cache hit
    t2 = registry.get_template_by_version_id(db_session, row.id, "rag_qa", "zh")
    assert t2.version_id == row.id

    # Invalidate all
    registry.invalidate_all()

    # After invalidation, should fall back to file default
    t3 = registry.get_template_by_version_id(db_session, row.id, "rag_qa", "zh")
    assert t3.version_id == default_version_id("rag_qa", "zh")


# I4: second-level fallback test
def test_second_level_fallback():
    t = registry.get_default_template("nonexistent_key", "fr")
    assert t.prompt_key == "rag_qa"
    assert t.lang == "zh"
    assert t.version_id == default_version_id("rag_qa", "zh")
