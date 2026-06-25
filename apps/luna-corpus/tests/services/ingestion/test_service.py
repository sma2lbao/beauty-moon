"""Tests for ingestion service."""
from unittest.mock import MagicMock

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
    storage.save = MagicMock(return_value="kb-1/abc/test.pdf")
    storage.delete = MagicMock()
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
def mock_processor():
    """Create mock document processor."""
    processor = MagicMock()
    processor.process_document = MagicMock(return_value=[])
    return processor


@pytest.fixture
def ingestion_service(mock_storage, mock_parser_registry, mock_processor):
    """Create ingestion service with mocked dependencies."""
    return IngestionService(
        storage=mock_storage,
        parser_registry=mock_parser_registry,
        processor=mock_processor,
        max_upload_size=52428800,
        duplicate_policy="reject",
    )


def test_ingest_file_success(ingestion_service, mock_storage, mock_processor):
    """Test successful file ingestion."""
    db = MagicMock()
    file = _mock_upload_file("test.pdf", "application/pdf", 1024, b"pdf content")

    # Mock hash check - no duplicate
    db.query.return_value.filter.return_value.first.return_value = None

    result = ingestion_service.ingest_file(db, file, "kb-1")

    assert isinstance(result, FileUpload)
    assert result.status == FileUploadStatus.PARSED
    mock_storage.save.assert_called_once()
    mock_processor.process_document.assert_called_once()
    db.add.assert_called()
    db.commit.assert_called()


def test_ingest_file_unsupported_type(ingestion_service, mock_parser_registry):
    """Test ingestion with unsupported file type."""
    mock_parser_registry.is_supported.return_value = False

    db = MagicMock()
    file = _mock_upload_file("test.unknown", "application/unknown", 1024, b"test")

    with pytest.raises(UnsupportedFileTypeError):
        ingestion_service.ingest_file(db, file, "kb-1")


def test_ingest_file_too_large(ingestion_service):
    """Test ingestion with file exceeding size limit."""
    db = MagicMock()
    file = _mock_upload_file("huge.pdf", "application/pdf", 100_000_000, b"x" * 100)

    with pytest.raises(HTTPException) as exc:
        ingestion_service.ingest_file(db, file, "kb-1")
    assert exc.value.status_code == 413


def test_ingest_file_duplicate_reject(ingestion_service):
    """Test duplicate file rejection."""
    db = MagicMock()
    # Simulate existing file with same hash
    existing = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = existing

    file = _mock_upload_file("test.pdf", "application/pdf", 1024, b"pdf content")

    with pytest.raises(DuplicateFileError):
        ingestion_service.ingest_file(db, file, "kb-1")


def test_ingest_file_parse_error(ingestion_service, mock_parser_registry):
    """Test handling of parse errors."""
    parser = MagicMock()
    parser.parse = MagicMock(side_effect=ParseError("Corrupted file"))
    mock_parser_registry.get_parser.return_value = parser

    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = None

    file = _mock_upload_file("corrupted.pdf", "application/pdf", 1024, b"bad content")

    result = ingestion_service.ingest_file(db, file, "kb-1")

    assert result.status == FileUploadStatus.ERROR
    assert "Corrupted file" in result.error_message


def test_delete_file(ingestion_service, mock_storage):
    """Test deleting a file and its document."""
    db = MagicMock()
    upload = MagicMock()
    upload.stored_name = "kb-1/abc/test.pdf"
    upload.document = MagicMock()
    upload.document.id = "doc-1"
    upload.knowledge_base_id = "kb-1"

    db.query.return_value.filter.return_value.first.return_value = upload

    ingestion_service.delete_file(db, "upload-1", "kb-1")

    mock_storage.delete.assert_called_once_with("kb-1/abc/test.pdf")
    db.delete.assert_called()
    db.commit.assert_called()


def test_delete_file_not_found(ingestion_service):
    """Test deleting a non-existent file."""
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = None

    with pytest.raises(HTTPException) as exc:
        ingestion_service.delete_file(db, "missing", "kb-1")
    assert exc.value.status_code == 404
