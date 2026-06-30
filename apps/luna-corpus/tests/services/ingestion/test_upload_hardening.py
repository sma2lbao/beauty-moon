"""Tests for upload hardening: empty file and actual-byte size."""
import io

import pytest
from fastapi import HTTPException, UploadFile

from app.services.ingestion.exceptions import EmptyFileError
from app.services.ingestion.service import IngestionService


class _Registry:
    def is_supported(self, mime_type):
        return True

    def list_supported_types(self):
        return ["text/plain"]


def _upload(content: bytes, size, content_type="text/plain"):
    file = UploadFile(filename="f.txt", file=io.BytesIO(content))
    file.size = size  # may be None or spoofed
    file.headers = {"content-type": content_type}
    return file


@pytest.mark.asyncio
async def test_empty_file_rejected():
    service = IngestionService(
        storage=object(), parser_registry=_Registry(), max_upload_size=1000
    )
    with pytest.raises(EmptyFileError):
        await service.ingest_file(db=None, file=_upload(b"", size=0), knowledge_base_id="kb")


@pytest.mark.asyncio
async def test_actual_bytes_exceed_limit_when_size_missing():
    service = IngestionService(
        storage=object(), parser_registry=_Registry(), max_upload_size=5
    )
    with pytest.raises(HTTPException) as exc:
        await service.ingest_file(
            db=None, file=_upload(b"x" * 50, size=None), knowledge_base_id="kb"
        )
    assert exc.value.status_code == 413
