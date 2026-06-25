"""Document parser protocol and built-in implementations."""
from typing import Protocol

from app.services.ingestion.exceptions import ParseError


class DocumentParser(Protocol):
    """Protocol for document-to-text parsers."""

    @property
    def supported_mime_types(self) -> set[str]:
        """Return supported MIME types."""
        ...

    def parse(self, content: bytes, filename: str) -> str:
        """Parse file bytes to text.

        Args:
            content: Raw file bytes
            filename: Original filename for context

        Returns:
            Extracted plain text

        Raises:
            ParseError: If parsing fails
        """
        ...


class PlainTextParser:
    """Parser for plain text files."""

    @property
    def supported_mime_types(self) -> set[str]:
        """Return supported MIME types."""
        return {"text/plain"}

    def parse(self, content: bytes, filename: str) -> str:
        """Parse plain text bytes to string.

        Args:
            content: Raw file bytes
            filename: Original filename

        Returns:
            Decoded text
        """
        try:
            return content.decode("utf-8")
        except UnicodeDecodeError as e:
            raise ParseError(f"Failed to decode text file: {e}") from e
