"""Exceptions for ingestion pipeline."""


class IngestionError(Exception):
    """Base exception for ingestion errors."""

    pass


class ParseError(IngestionError):
    """Raised when file parsing fails."""

    pass


class UnsupportedFileTypeError(IngestionError):
    """Raised when file type is not supported."""

    pass


class StorageError(IngestionError):
    """Raised when storage operation fails."""

    pass


class DuplicateFileError(IngestionError):
    """Raised when a duplicate file is detected and policy is reject."""

    pass
