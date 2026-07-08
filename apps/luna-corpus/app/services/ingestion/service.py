"""Ingestion service orchestrating upload, storage, parse, document creation."""

import contextlib
import hashlib
import logging
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.db.models import ContentStatus, Document, FileUpload, FileUploadStatus
from app.db.vectorstore import delete_chunks_from_vectorstore
from app.metadata.validation import validate_and_normalize
from app.retrieval.bm25 import invalidate_bm25_cache
from app.services.document_identity import (
    ChangeType,
    compute_content_hash,
    resolve_document_identity,
)
from app.services.ingestion.exceptions import (
    EmptyFileError,
    ParseError,
    StorageError,
    UnsupportedFileTypeError,
)
from app.services.ingestion.parsers import ParserRegistry
from app.services.ingestion.storage import StorageBackend

logger = logging.getLogger(__name__)


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
    ):
        """Initialize ingestion service.

        Args:
            storage: Storage backend instance
            parser_registry: Parser registry instance
            max_upload_size: Maximum allowed file size in bytes
        """
        self.storage = storage
        self.parser_registry = parser_registry
        self.max_upload_size = max_upload_size

    async def ingest_file(
        self,
        db: Session,
        file: UploadFile,
        knowledge_base_id: str,
        metadata: dict | None = None,
        external_id: str | None = None,
    ) -> tuple[FileUpload | None, Document | None, str | None]:
        """Ingest a file with change detection.

        Returns (FileUpload | None, Document | None, change_type). change_type
        is one of ChangeType.value ("created"/"updated"/"unchanged"), or None
        when parsing failed. Vectorization is the caller's responsibility.
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

        # Validate & normalize metadata before any write.
        normalized_metadata = validate_and_normalize(db, knowledge_base_id, metadata)

        # Read content and compute file-byte hash (kept for file-layer record).
        content = file.file.read()
        content_hash = _compute_hash(content)
        file.file.seek(0)

        if len(content) == 0:
            raise EmptyFileError("Uploaded file is empty")

        if len(content) > self.max_upload_size:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail=f"File too large. Maximum size: {self.max_upload_size} bytes",
            )

        filename = file.filename or "unknown"
        stored_name = _generate_storage_path(knowledge_base_id, filename)

        # Create FileUpload record first (records the upload attempt; kept even
        # on parse failure so the error is queryable).
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
            await self.storage.save(file, stored_name)

            parser = self.parser_registry.get_parser(mime_type)
            parsed_text = parser.parse(content, filename)
            text_hash = compute_content_hash(parsed_text)

            existing = resolve_document_identity(
                db,
                knowledge_base_id,
                external_id=external_id,
                original_name=filename,
            )

            has_tables = "|" in parsed_text and "---" in parsed_text
            has_code = "```" in parsed_text or "def " in parsed_text

            if existing is None:
                # created
                document = Document(
                    knowledge_base_id=knowledge_base_id,
                    file_id=upload.id,
                    external_id=external_id,
                    title=filename or "Untitled",
                    content=parsed_text,
                    content_hash=text_hash,
                    version=1,
                    source=f"file://{filename}",
                    has_tables=has_tables,
                    has_code=has_code,
                    status=ContentStatus.PENDING,
                    doc_metadata=normalized_metadata or None,
                )
                db.add(document)
                db.commit()
                db.refresh(document)
                upload.status = FileUploadStatus.PARSED
                upload.parsed_at = datetime.now()
                db.commit()
                db.refresh(upload)
                return upload, document, ChangeType.CREATED.value

            if existing.content_hash == text_hash:
                # unchanged: roll back this redundant upload, keep existing doc.
                old_file = existing.file
                await self._discard_upload(db, upload)
                return old_file, existing, ChangeType.UNCHANGED.value

            # updated: update the existing document in place, repoint file_id,
            # delete the previously stored file.
            old_upload = existing.file
            existing.content = parsed_text
            existing.content_hash = text_hash
            existing.version = existing.version + 1
            existing.title = filename or existing.title
            existing.source = f"file://{filename}"
            existing.has_tables = has_tables
            existing.has_code = has_code
            existing.status = ContentStatus.PENDING
            existing.file_id = upload.id
            if external_id:
                existing.external_id = external_id
            if normalized_metadata:
                existing.doc_metadata = normalized_metadata
            upload.status = FileUploadStatus.PARSED
            upload.parsed_at = datetime.now()
            db.commit()
            db.refresh(existing)
            if old_upload is not None and old_upload.id != upload.id:
                await self._discard_upload(db, old_upload)
            return upload, existing, ChangeType.UPDATED.value

        except ParseError as e:
            upload.status = FileUploadStatus.ERROR
            upload.error_message = str(e)
            db.commit()
            with contextlib.suppress(StorageError):
                await self.storage.delete(stored_name)
            return upload, None, None

        except Exception as e:
            upload.status = FileUploadStatus.ERROR
            upload.error_message = str(e)
            db.commit()
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
            with contextlib.suppress(StorageError):
                await self.storage.delete(stored_name)
            return upload, None, None

    async def _discard_upload(self, db: Session, upload: FileUpload) -> None:
        """Delete a FileUpload row and its stored file (no document touched)."""
        with contextlib.suppress(StorageError):
            await self.storage.delete(upload.stored_name)
        try:
            db.delete(upload)
            db.commit()
        except Exception:
            db.rollback()
            logger.warning("Failed to discard FileUpload %s; leaving orphan row", upload.id)

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
