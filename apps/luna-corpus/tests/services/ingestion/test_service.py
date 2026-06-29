"""Tests for ingestion service."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.db.models import FileUpload, FileUploadStatus
from app.services.ingestion.exceptions import (
    DuplicateFileError,
    ParseError,
    UnsupportedFileTypeError,
)
from app.services.ingestion.service import IngestionService


def _mock_upload_file(filename, content_type, size, content):
    """Create a mock UploadFile with proper file.file.read() support."""
    file = MagicMock()
    file.filename = filename
    file.content_type = content_type
    file.size = size
    # FastAPI UploadFile exposes .file which is a SpooledTemporaryFile-like object
    file.file = MagicMock()
    file.file.read = MagicMock(return_value=content)
    file.file.seek = MagicMock()
    return file


@pytest.fixture
def mock_storage():
    """Create mock storage backend."""
    storage = MagicMock()
    storage.save = AsyncMock(return_value="kb-1/abc/test.pdf")
    storage.delete = AsyncMock()
    return storage


@pytest.fixture
def mock_parser_registry():
    """Create mock parser registry."""
    registry = MagicMock()
    registry.is_supported = MagicMock(return_value=True)
    parser = MagicMock()
    parser.parse = MagicMock(return_value="Parsed content")
    registry.get_parser = MagicMock(return_value=parser)
    return registry


@pytest.fixture
def ingestion_service(mock_storage, mock_parser_registry):
    """Create ingestion service with mocked dependencies."""
    return IngestionService(
        storage=mock_storage,
        parser_registry=mock_parser_registry,
        max_upload_size=52428800,
        duplicate_policy="reject",
    )


@pytest.mark.asyncio
async def test_ingest_file_success(ingestion_service, mock_storage):
    """Test successful file ingestion returns FileUpload and Document."""
    db = MagicMock()
    file = _mock_upload_file("test.pdf", "application/pdf", 1024, b"pdf content")

    # Mock hash check - no duplicate
    db.query.return_value.filter.return_value.first.return_value = None

    upload, document = await ingestion_service.ingest_file(db, file, "kb-1")

    assert isinstance(upload, FileUpload)
    assert upload.status == FileUploadStatus.UPLOADED
    mock_storage.save.assert_called_once()
    db.add.assert_called()
    db.commit.assert_called()
    # Document was created but NOT processed
    assert document is not None


@pytest.mark.asyncio
async def test_ingest_file_unsupported_type(ingestion_service, mock_parser_registry):
    """Test ingestion with unsupported file type."""
    mock_parser_registry.is_supported.return_value = False

    db = MagicMock()
    file = _mock_upload_file("test.unknown", "application/unknown", 1024, b"test")

    with pytest.raises(UnsupportedFileTypeError):
        await ingestion_service.ingest_file(db, file, "kb-1")


@pytest.mark.asyncio
async def test_ingest_file_too_large(ingestion_service):
    """Test ingestion with file exceeding size limit."""
    db = MagicMock()
    file = _mock_upload_file("huge.pdf", "application/pdf", 100_000_000, b"x" * 100)

    with pytest.raises(HTTPException) as exc:
        await ingestion_service.ingest_file(db, file, "kb-1")
    assert exc.value.status_code == 413


@pytest.mark.asyncio
async def test_ingest_file_duplicate_reject(ingestion_service):
    """Test duplicate file rejection."""
    db = MagicMock()
    # Simulate existing file with same hash
    existing = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = existing

    file = _mock_upload_file("test.pdf", "application/pdf", 1024, b"pdf content")

    with pytest.raises(DuplicateFileError):
        await ingestion_service.ingest_file(db, file, "kb-1")


@pytest.mark.asyncio
async def test_ingest_file_duplicate_replace(mock_storage, mock_parser_registry):
    """Test duplicate file replace policy."""
    service = IngestionService(
        storage=mock_storage,
        parser_registry=mock_parser_registry,
        max_upload_size=52428800,
        duplicate_policy="replace",
    )
    db = MagicMock()
    existing = MagicMock()
    existing.id = "existing-id"
    existing.original_name = "old.pdf"
    existing.stored_name = "kb-1/old/old.pdf"
    existing.document = None
    db.query.return_value.filter.return_value.first.side_effect = [
        existing,  # duplicate check in ingest_file
        existing,  # lookup in delete_file
        None,  # no duplicate after delete
    ]

    file = _mock_upload_file("test.pdf", "application/pdf", 1024, b"pdf content")

    upload, _ = await service.ingest_file(db, file, "kb-1")

    assert isinstance(upload, FileUpload)
    mock_storage.delete.assert_called_once()
    db.delete.assert_called()


@pytest.mark.asyncio
async def test_ingest_file_parse_error(ingestion_service, mock_parser_registry):
    """Test handling of parse errors."""
    parser = MagicMock()
    parser.parse = MagicMock(side_effect=ParseError("Corrupted file"))
    mock_parser_registry.get_parser.return_value = parser

    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = None

    file = _mock_upload_file("corrupted.pdf", "application/pdf", 1024, b"bad content")

    result = await ingestion_service.ingest_file(db, file, "kb-1")

    assert result[0].status == FileUploadStatus.ERROR
    assert "Corrupted file" in result[0].error_message
    assert result[1] is None


@pytest.mark.asyncio
async def test_delete_file(ingestion_service, mock_storage):
    """Test deleting a file and its document."""
    db = MagicMock()
    upload = MagicMock()
    upload.stored_name = "kb-1/abc/test.pdf"
    upload.document = MagicMock()
    upload.document.id = "doc-1"
    chunk_mock = MagicMock()
    chunk_mock.id = "chunk-1"
    upload.document.chunks = [chunk_mock]
    upload.knowledge_base_id = "kb-1"

    db.query.return_value.filter.return_value.first.return_value = upload

    with patch(
        "app.services.ingestion.service.delete_chunks_from_vectorstore"
    ) as mock_del_vectors:
        await ingestion_service.delete_file(db, "upload-1", "kb-1")

    mock_del_vectors.assert_called_once_with(["chunk-1"])
    mock_storage.delete.assert_called_once_with("kb-1/abc/test.pdf")
    db.delete.assert_called()
    db.commit.assert_called()


@pytest.mark.asyncio
async def test_delete_file_not_found(ingestion_service):
    """Test deleting a non-existent file."""
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = None

    with pytest.raises(HTTPException) as exc:
        await ingestion_service.delete_file(db, "missing", "kb-1")
    assert exc.value.status_code == 404
