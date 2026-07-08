"""全库分面聚合测试（内存 SQLite + 真实 ORM）。"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.models import (
    Base,
    ContentStatus,
    Document,
    KnowledgeBase,
    Tenant,
    Workspace,
)
from app.metadata.facets import compute_facets
from app.metadata.models import MetadataFieldDefinition


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
    engine.dispose()


def _field(db, **kw):
    db.add(MetadataFieldDefinition(knowledge_base_id=db.kb_id, **kw))
    db.flush()


def _doc(db, meta, status=ContentStatus.COMPLETED):
    db.add(Document(
        knowledge_base_id=db.kb_id, title="t", content="c",
        status=status, doc_metadata=meta,
    ))
    db.flush()


def _facet(facets, key):
    return next(f for f in facets if f["key"] == key)


def test_enum_facet_counts(db):
    _field(db, key="category", label="类别", field_type="enum")
    _doc(db, {"category": "合同"})
    _doc(db, {"category": "合同"})
    _doc(db, {"category": "发票"})
    facets = compute_facets(db, db.kb_id)
    buckets = _facet(facets, "category")["buckets"]
    assert buckets[0] == {"value": "合同", "count": 2}
    assert {"value": "发票", "count": 1} in buckets


def test_only_completed_documents_counted(db):
    _field(db, key="category", label="类别", field_type="enum")
    _doc(db, {"category": "合同"})
    _doc(db, {"category": "合同"}, status=ContentStatus.PENDING)
    buckets = _facet(compute_facets(db, db.kb_id), "category")["buckets"]
    assert buckets == [{"value": "合同", "count": 1}]


def test_is_facetable_false_excluded(db):
    _field(db, key="secret", label="隐藏", field_type="string",
           is_facetable=False)
    _doc(db, {"secret": "x"})
    assert all(f["key"] != "secret" for f in compute_facets(db, db.kb_id))


def test_tags_facet_multi_count(db):
    _field(db, key="tags", label="标签", field_type="tags")
    _doc(db, {"tags": ["a", "b"]})
    _doc(db, {"tags": ["a"]})
    buckets = _facet(compute_facets(db, db.kb_id), "tags")["buckets"]
    assert buckets[0] == {"value": "a", "count": 2}
    assert {"value": "b", "count": 1} in buckets


def test_date_bucketed_by_month(db):
    _field(db, key="d", label="日期", field_type="date")
    _doc(db, {"d": "2025-03-01"})
    _doc(db, {"d": "2025-03-20"})
    _doc(db, {"d": "2025-02-10"})
    buckets = _facet(compute_facets(db, db.kb_id), "d")["buckets"]
    assert {"value": "2025-03", "count": 2} in buckets
    assert {"value": "2025-02", "count": 1} in buckets


def test_number_equal_width_buckets(db):
    _field(db, key="amount", label="金额", field_type="number")
    for v in [0.0, 50.0, 100.0]:
        _doc(db, {"amount": v})
    buckets = _facet(compute_facets(db, db.kb_id), "amount")["buckets"]
    assert sum(b["count"] for b in buckets) == 3
    assert len(buckets) <= 5


def test_string_top_20(db):
    _field(db, key="author", label="作者", field_type="string")
    for i in range(25):
        _doc(db, {"author": f"a{i}"})
    buckets = _facet(compute_facets(db, db.kb_id), "author")["buckets"]
    assert len(buckets) == 20
