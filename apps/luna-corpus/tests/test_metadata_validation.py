"""元数据校验与归一化测试（用内存 SQLite + 真实 ORM）。"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.models import Base, KnowledgeBase, Tenant, Workspace
from app.metadata.models import MetadataFieldDefinition
from app.metadata.validation import (
    MetadataValidationError,
    validate_and_normalize,
)


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    tenant = Tenant(name="T", slug="t")
    session.add(tenant)
    session.flush()
    ws = Workspace(tenant_id=tenant.id, name="W", slug="w")
    session.add(ws)
    session.flush()
    kb = KnowledgeBase(workspace_id=ws.id, name="KB", slug="kb")
    session.add(kb)
    session.flush()
    session.kb_id = kb.id
    yield session
    session.close()


def _add_field(db, **kwargs):
    f = MetadataFieldDefinition(knowledge_base_id=db.kb_id, **kwargs)
    db.add(f)
    db.flush()
    return f


def test_empty_metadata_no_required_returns_empty(db):
    assert validate_and_normalize(db, db.kb_id, None) == {}
    assert validate_and_normalize(db, db.kb_id, {}) == {}


def test_enum_valid(db):
    _add_field(db, key="category", label="类别", field_type="enum",
               options=["合同", "发票"])
    out = validate_and_normalize(db, db.kb_id, {"category": " 合同 "})
    assert out == {"category": "合同"}


def test_enum_not_in_options_raises(db):
    _add_field(db, key="category", label="类别", field_type="enum",
               options=["合同"])
    with pytest.raises(MetadataValidationError) as e:
        validate_and_normalize(db, db.kb_id, {"category": "发票"})
    assert any("category" in msg for msg in e.value.errors)


def test_unknown_key_raises(db):
    with pytest.raises(MetadataValidationError) as e:
        validate_and_normalize(db, db.kb_id, {"nope": "x"})
    assert any("nope" in msg for msg in e.value.errors)


def test_required_missing_raises(db):
    _add_field(db, key="category", label="类别", field_type="string",
               required=True)
    with pytest.raises(MetadataValidationError):
        validate_and_normalize(db, db.kb_id, {})


def test_date_normalized(db):
    _add_field(db, key="published_at", label="发布", field_type="date")
    out = validate_and_normalize(db, db.kb_id, {"published_at": "2025-03-01"})
    assert out == {"published_at": "2025-03-01"}


def test_date_invalid_raises(db):
    _add_field(db, key="published_at", label="发布", field_type="date")
    with pytest.raises(MetadataValidationError):
        validate_and_normalize(db, db.kb_id, {"published_at": "not-a-date"})


def test_number_coerced(db):
    _add_field(db, key="amount", label="金额", field_type="number")
    out = validate_and_normalize(db, db.kb_id, {"amount": "100.5"})
    assert out == {"amount": 100.5}


def test_number_invalid_raises(db):
    _add_field(db, key="amount", label="金额", field_type="number")
    with pytest.raises(MetadataValidationError):
        validate_and_normalize(db, db.kb_id, {"amount": "abc"})


def test_tags_dedup_and_trim(db):
    _add_field(db, key="tags", label="标签", field_type="tags")
    out = validate_and_normalize(
        db, db.kb_id, {"tags": [" a ", "b", "a", ""]}
    )
    assert out == {"tags": ["a", "b"]}
