"""Chunk 定位列的 ORM 层测试（内存 SQLite）。"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.models import Base, Chunk, ContentType


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_chunk_locator_columns_persist():
    db = _session()
    chunk = Chunk(
        document_id="doc1",
        content="正文",
        content_type=ContentType.TEXT,
        chunk_index=0,
        char_start=10,
        char_end=12,
        heading_path="第2章 > 2.1 安装",
    )
    db.add(chunk)
    db.commit()

    row = db.query(Chunk).first()
    assert row.char_start == 10
    assert row.char_end == 12
    assert row.heading_path == "第2章 > 2.1 安装"


def test_chunk_locator_columns_nullable():
    db = _session()
    chunk = Chunk(
        document_id="doc1",
        content="正文",
        content_type=ContentType.TEXT,
        chunk_index=0,
    )
    db.add(chunk)
    db.commit()

    row = db.query(Chunk).first()
    assert row.char_start is None
    assert row.char_end is None
    assert row.heading_path is None
