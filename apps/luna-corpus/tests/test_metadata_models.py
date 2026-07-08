"""MetadataFieldDefinition ORM 与 Document.doc_metadata 列测试。"""
from app.db.models import Document
from app.metadata.models import MetadataFieldDefinition


def test_metadata_field_definition_table():
    assert MetadataFieldDefinition.__tablename__ == "metadata_field_definitions"
    cols = set(MetadataFieldDefinition.__table__.columns.keys())
    assert {
        "id", "knowledge_base_id", "key", "label", "field_type",
        "options", "required", "is_facetable", "created_at", "updated_at",
    } <= cols


def test_metadata_field_definition_unique_constraint():
    uniques = [
        c for c in MetadataFieldDefinition.__table__.constraints
        if c.__class__.__name__ == "UniqueConstraint"
    ]
    cols = {tuple(sorted(col.name for col in u.columns)) for u in uniques}
    assert ("key", "knowledge_base_id") in cols


def test_document_has_doc_metadata_column():
    assert "doc_metadata" in Document.__table__.columns.keys()
