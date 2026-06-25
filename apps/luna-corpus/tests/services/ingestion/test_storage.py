"""Tests for ingestion ingestion storage backend."""
import io
from pathlib import Path

import pytest
from fastapi import UploadFile

from app.services.ingestion.exceptions import StorageError
from app.services.ingestion.storage import LocalStorageBackend, get_storage_backend


@pytest.fixture
def temp_storage_path(tmp_path):
    """Provide a temporary storage directory."""
    return tmp_path / "uploads"


@pytest.fixture
def local_backend(temp_storage_path):
    """Create a LocalStorageBackend instance."""
    return LocalStorageBackend(base_path=temp_storage_path)


@pytest.fixture
def sample_upload_file():
    """Create a sample UploadFile for testing."""
    return UploadFile(filename="test.txt", file=io.BytesIO(b"Hello, world!"))


@pytest.mark.asyncio
async def test_local_storage_save(local_backend, temp_storage_path, sample_upload_file):
    """Test saving a file to local storage."""
    stored_path = await local_backend.save(sample_upload_file, "kb-1/abc/test.txt")
    assert stored_path == "kb-1/abc/test.txt"
    assert (temp_storage_path / "kb-1" / "abc" / "test.txt").exists()
    with open(temp_storage_path / "kb-1" / "abc" / "test.txt", "rb") as f:
        assert f.read() == b"Hello, world!"


@pytest.mark.asyncio
async def test_local_storage_read(local_backend, sample_upload_file):
    """Test reading a file from local storage."""
    await local_backend.save(sample_upload_file, "kb-1/abc/test.txt")
    content = await local_backend.read("kb-1/abc/test.txt")
    assert content == b"Hello, world!"


@pytest.mark.asyncio
async def test_local_storage_delete(local_backend, sample_upload_file):
    """Test deleting a file from local storage."""
    await local_backend.save(sample_upload_file, "kb-1/abc/test.txt")
    await local_backend.delete("kb-1/abc/test.txt")
    assert not (local_backend.base_path / "kb-1" / "abc" / "test.txt").exists()


def test_local_storage_get_url(local_backend):
    """Test get_url returns None for local storage."""
    assert local_backend.get_url("kb-1/abc/test.txt") is None


@pytest.mark.asyncio
async def test_local_storage_read_not_found(local_backend):
    """Test reading a non-existent file raises StorageError."""
    with pytest.raises(StorageError, match="File not found"):
        await local_backend.read("kb-1/missing.txt")


@pytest.mark.asyncio
async def test_local_storage_delete_not_found(local_backend):
    """Test deleting a non-existent file raises StorageError."""
    with pytest.raises(StorageError, match="File not found"):
        await local_backend.delete("kb-1/missing.txt")


def test_get_storage_backend_returns_local(monkeypatch, tmp_path):
    """Test factory returns LocalStorageBackend by default."""
    from app.core.config import Settings
    settings = Settings(storage_backend="local", storage_local_path=tmp_path / "uploads")
    monkeypatch.setattr("app.services.ingestion.storage.get_settings", lambda: settings)
    backend = get_storage_backend()
    assert isinstance(backend, LocalStorageBackend)
