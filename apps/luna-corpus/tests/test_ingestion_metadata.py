"""摄取服务元数据校验测试。"""
import io
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import UploadFile

from app.db import models as _db_models  # noqa: F401 保证 ORM 关系解析

from app.metadata.validation import MetadataValidationError
from app.services.ingestion.service import IngestionService


def _service():
    storage = MagicMock()
    storage.save = AsyncMock()
    storage.delete = AsyncMock()
    registry = MagicMock()
    registry.is_supported.return_value = True
    parser = MagicMock()
    parser.parse.return_value = "parsed text"
    registry.get_parser.return_value = parser
    return IngestionService(storage=storage, parser_registry=registry)


def _upload():
    f = UploadFile(filename="a.txt", file=io.BytesIO(b"hello"))
    f._content_type = "text/plain"
    return f


@pytest.mark.asyncio
async def test_invalid_metadata_rejects_before_persist():
    service = _service()
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = None
    with patch(
        "app.services.ingestion.service.validate_and_normalize",
        side_effect=MetadataValidationError(["坏字段"]),
    ):
        with pytest.raises(MetadataValidationError):
            await service.ingest_file(
                db, _upload(), "kb1", metadata={"x": "y"}
            )
    # 校验失败：未提交文件记录
    db.add.assert_not_called()
