"""Storage backend abstraction and local filesystem implementation."""
from pathlib import Path
from typing import Protocol

from fastapi import UploadFile

from app.core.config import get_settings
from app.services.ingestion.exceptions import StorageError


class StorageBackend(Protocol):
    """Abstract storage backend protocol."""

    async def save(self, file: UploadFile, path: str) -> str:
        """Save file, return stored path/identifier."""
        ...

    async def read(self, path: str) -> bytes:
        """Read file content as bytes."""
        ...

    async def delete(self, path: str) -> None:
        """Delete file."""
        ...

    def get_url(self, path: str) -> str | None:
        """Return public URL if available, else None."""
        ...


class LocalStorageBackend:
    """Local filesystem storage backend."""

    def __init__(self, base_path: str | None = None):
        """Initialize with base path.

        Args:
            base_path: Base directory for file storage. Defaults to settings.
        """
        if base_path is None:
            base_path = get_settings().storage_local_path
        self.base_path = Path(base_path)
        self.base_path.mkdir(parents=True, exist_ok=True)

    async def save(self, file: UploadFile, path: str) -> str:
        """Save file to local filesystem.

        Args:
            file: Uploaded file
            path: Relative path within base_path

        Returns:
            Stored path (same as input path)
        """
        target = self.base_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        content = await file.read()
        target.write_bytes(content)
        await file.seek(0)
        return path

    async def read(self, path: str) -> bytes:
        """Read file from local filesystem.

        Args:
            path: Relative path within base_path

        Returns:
            File content as bytes

        Raises:
            StorageError: If file does not exist
        """
        target = self.base_path / path
        if not target.exists():
            raise StorageError(f"File not found: {path}")
        return target.read_bytes()

    async def delete(self, path: str) -> None:
        """Delete file from local filesystem.

        Args:
            path: Relative path within base_path

        Raises:
            StorageError: If file does not exist
        """
        target = self.base_path / path
        if not target.exists():
            raise StorageError(f"File not found: {path}")
        target.unlink()

    def get_url(self, path: str) -> str | None:
        """Return public URL. Local storage has no public URL."""
        return None


def get_storage_backend() -> StorageBackend:
    """Get configured storage backend instance.

    Returns:
        StorageBackend instance
    """
    settings = get_settings()
    return LocalStorageBackend(base_path=settings.storage_local_path)
