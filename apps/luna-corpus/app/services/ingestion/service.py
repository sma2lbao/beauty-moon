"""Ingestion service orchestrating upload, storage, parse, document creation."""

import contextlib
import hashlib
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.db.models import ContentStatus, Document, FileUpload, FileUploadStatus
from app.db.vectorstore import delete_chunks_from_vectorstore
from app.retrieval.bm25 import invalidate_bm25_cache
from app.services.ingestion.exceptions import (
    DuplicateFileError,
    EmptyFileError,
    ParseError,
    StorageError,
    UnsupportedFileTypeError,
)
from app.services.ingestion.parsers import ParserRegistry
from app.services.ingestion.storage import StorageBackend


def _safe_filename(filename: str) -> str:
    """Sanitize filename to prevent path traversal.

    Args:
        filename: Original filename

    Returns:
        Safe filename with path traversal characters removed
    """
    return Path(filename).name


def _compute_hash(content: bytes) -> str:
    """Compute SHA-256 hash of file content.

    Args:
        content: File bytes

    Returns:
        Hex digest of SHA-256
    """
    return hashlib.sha256(content).hexdigest()


def _generate_storage_path(
    knowledge_base_id: str,
    original_name: str,
) -> str:
    """Generate a storage path for an uploaded file.

    Args:
        knowledge_base_id: Knowledge base ID
        original_name: Original filename

    Returns:
        Relative storage path
    """
    file_uuid = str(uuid.uuid4())
    safe_name = _safe_filename(original_name)
    return f"{knowledge_base_id}/{file_uuid}/{safe_name}"


class IngestionService:
    """Orchestrate file upload -> storage -> parse -> document creation."""

    def __init__(
        self,
        storage: StorageBackend,
        parser_registry: ParserRegistry,
        max_upload_size: int = 52428800,
        duplicate_policy: str = "reject",
    ):
        """Initialize ingestion service.

        Args:
            storage: Storage backend instance
            parser_registry: Parser registry instance
            max_upload_size: Maximum allowed file size in bytes
            duplicate_policy: How to handle duplicate files: "reject" or "replace"
        """
        self.storage = storage
        self.parser_registry = parser_registry
        self.max_upload_size = max_upload_size
        self.duplicate_policy = duplicate_policy

    async def ingest_file(
        self,
        db: Session,
        file: UploadFile,
        knowledge_base_id: str,
    ) -> tuple[FileUpload, Document | None]:
        """Ingest a file: store, parse, create document. Returns (FileUpload, Document).

        Document processing (chunk + vectorize) is the caller's responsibility.
        """
        # Validate file size
        if file.size and file.size > self.max_upload_size:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail=f"File too large. Maximum size: {self.max_upload_size} bytes",
            )

        # Validate MIME type
        mime_type = file.content_type or "application/octet-stream"
        if not self.parser_registry.is_supported(mime_type):
            supported = ", ".join(self.parser_registry.list_supported_types())
            raise UnsupportedFileTypeError(
                f"Unsupported file type: {mime_type}. Supported: {supported}"
            )

        # Read content and compute hash
        content = file.file.read()
        content_hash = _compute_hash(content)
        file.file.seek(0)

        # Reject empty files
        if len(content) == 0:
            raise EmptyFileError("Uploaded file is empty")

        # Enforce actual-byte size (defends against missing/spoofed Content-Length)
        if len(content) > self.max_upload_size:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail=f"File too large. Maximum size: {self.max_upload_size} bytes",
            )

        # Check for duplicates
        existing = (
            db.query(FileUpload)
            .filter(
                FileUpload.knowledge_base_id == knowledge_base_id,
                FileUpload.content_hash == content_hash,
            )
            .first()
        )
        if existing:
            if self.duplicate_policy == "reject":
                raise DuplicateFileError(
                    f"File already exists: {existing.original_name}"
                )
            # replace policy: delete old file and continue
            await self.delete_file(db, existing.id, knowledge_base_id)

        # Generate storage path and save file
        filename = file.filename or "unknown"
        stored_name = _generate_storage_path(knowledge_base_id, filename)

        # Create FileUpload record first
        upload = FileUpload(
            knowledge_base_id=knowledge_base_id,
            original_name=filename,
            stored_name=stored_name,
            mime_type=mime_type,
            size_bytes=file.size or len(content),
            content_hash=content_hash,
            status=FileUploadStatus.UPLOADED,
        )
        db.add(upload)
        db.commit()
        db.refresh(upload)

        try:
            # Save to storage
            await self.storage.save(file, stored_name)

            # Parse content
            parser = self.parser_registry.get_parser(mime_type)
            parsed_text = parser.parse(content, filename)

            # Create Document
            document = Document(
                knowledge_base_id=knowledge_base_id,
                file_id=upload.id,
                title=filename or "Untitled",
                content=parsed_text,
                source=f"file://{filename}",
                has_tables="|" in parsed_text and "---" in parsed_text,
                has_code="```" in parsed_text or "def " in parsed_text,
                status=ContentStatus.PENDING,
            )
            db.add(document)
            db.commit()
            db.refresh(document)

            # Parsing succeeded: mark the file as parsed. Vectorization is the
            # caller's responsibility (handled asynchronously) and is tracked
            # separately on Document.status / IngestionTask.status.
            upload.status = FileUploadStatus.PARSED
            upload.parsed_at = datetime.now()
            db.commit()
            db.refresh(upload)

            return upload, document

        except ParseError as e:
            upload.status = FileUploadStatus.ERROR
            upload.error_message = str(e)
            db.commit()
            # Clean up stored file
            with contextlib.suppress(StorageError):
                await self.storage.delete(stored_name)
            return upload, None

        except Exception as e:
            upload.status = FileUploadStatus.ERROR
            upload.error_message = str(e)
            db.commit()
            # Rollback: delete document if created
            doc = (
                db.query(Document)
                .filter(
                    Document.file_id == upload.id,
                    Document.knowledge_base_id == knowledge_base_id,
                )
                .first()
            )
            if doc:
                db.delete(doc)
                db.commit()
            # Clean up stored file
            with contextlib.suppress(StorageError):
                await self.storage.delete(stored_name)
            return upload, None

    async def delete_file(
        self,
        db: Session,
        file_id: str,
        knowledge_base_id: str,
    ) -> None:
        """Delete a file and its associated document, chunks, vectors.

        Args:
            db: Database session
            file_id: FileUpload ID
            knowledge_base_id: Knowledge base ID for scoping

        Raises:
            HTTPException: 404 if file not found or not in knowledge base
        """
        upload = (
            db.query(FileUpload)
            .filter(
                FileUpload.id == file_id,
                FileUpload.knowledge_base_id == knowledge_base_id,
            )
            .first()
        )
        if not upload:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="File not found",
            )

        # Delete chunks from vector store before deleting document
        if upload.document and upload.document.chunks:
            delete_chunks_from_vectorstore([c.id for c in upload.document.chunks])

        # Drop keyword index so deleted chunks stop matching.
        invalidate_bm25_cache(knowledge_base_id)

        # Delete associated document (which cascades to chunks in SQL)
        if upload.document:
            db.delete(upload.document)

        # Delete from storage
        with contextlib.suppress(StorageError):
            await self.storage.delete(upload.stored_name)

        # Delete upload record
        db.delete(upload)
        db.commit()
