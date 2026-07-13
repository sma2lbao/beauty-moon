"""SourceResponse 定位字段的序列化测试。"""
from app.api.routes import SourceResponse


def test_source_response_accepts_locator_fields():
    src = SourceResponse(
        document_id="d1",
        chunk_content="片段",
        relevance_score=0.9,
        chunk_index=3,
        char_start=100,
        char_end=130,
        heading_path="第2章 > 2.1 安装",
    )
    assert src.chunk_index == 3
    assert src.char_start == 100
    assert src.char_end == 130
    assert src.heading_path == "第2章 > 2.1 安装"


def test_source_response_locator_defaults_none():
    # 老客户端/存量数据：不传定位字段应默认 None，保持向后兼容
    src = SourceResponse(
        document_id="d1",
        chunk_content="片段",
        relevance_score=0.5,
    )
    assert src.chunk_index is None
    assert src.char_start is None
    assert src.char_end is None
    assert src.heading_path is None
