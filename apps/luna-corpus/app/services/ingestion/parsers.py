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


class PyPDFParser:
    """Parser for PDF files using pypdf."""

    @property
    def supported_mime_types(self) -> set[str]:
        """Return supported MIME types."""
        return {"application/pdf"}

    def parse(self, content: bytes, filename: str) -> str:
        """Extract text from PDF.

        Args:
            content: Raw PDF bytes
            filename: Original filename

        Returns:
            Extracted text
        """
        from io import BytesIO

        from pypdf import PdfReader

        try:
            reader = PdfReader(BytesIO(content))
            texts = []
            for page in reader.pages:
                text = page.extract_text()
                if text:
                    texts.append(text)
            return "\n\n".join(texts)
        except Exception as e:
            raise ParseError(f"Failed to parse PDF: {e}") from e


class DocxParser:
    """Parser for DOCX files using python-docx."""

    @property
    def supported_mime_types(self) -> set[str]:
        """Return supported MIME types."""
        return {
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        }

    def parse(self, content: bytes, filename: str) -> str:
        """Extract text from DOCX.

        Args:
            content: Raw DOCX bytes
            filename: Original filename

        Returns:
            Extracted text
        """
        from io import BytesIO

        from docx import Document

        try:
            doc = Document(BytesIO(content))
            texts = []
            for para in doc.paragraphs:
                if para.text:
                    texts.append(para.text)
            return "\n".join(texts)
        except Exception as e:
            raise ParseError(f"Failed to parse DOCX: {e}") from e


class HTMLParser:
    """Parser for HTML files using BeautifulSoup."""

    @property
    def supported_mime_types(self) -> set[str]:
        """Return supported MIME types."""
        return {"text/html"}

    def parse(self, content: bytes, filename: str) -> str:
        """Extract text from HTML.

        Args:
            content: Raw HTML bytes
            filename: Original filename

        Returns:
            Extracted text with tags stripped
        """
        from bs4 import BeautifulSoup

        try:
            soup = BeautifulSoup(content, "html.parser")
            # Remove script and style elements
            for tag in soup(["script", "style"]):
                tag.decompose()
            text = soup.get_text(separator="\n")
            # Clean up blank lines
            lines = (line.strip() for line in text.splitlines())
            return "\n".join(line for line in lines if line)
        except Exception as e:
            raise ParseError(f"Failed to parse HTML: {e}") from e


class MarkdownParser:
    """Parser for Markdown files."""

    @property
    def supported_mime_types(self) -> set[str]:
        """Return supported MIME types."""
        return {"text/markdown", "text/x-markdown"}

    def parse(self, content: bytes, filename: str) -> str:
        """Convert Markdown to plain text.

        Args:
            content: Raw Markdown bytes
            filename: Original filename

        Returns:
            Plain text with Markdown formatting removed
        """
        import re

        try:
            text = content.decode("utf-8")
            # Remove headers
            text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
            # Remove bold/italic markers
            text = re.sub(r"\*\*|__", "", text)
            text = re.sub(r"\*|_", "", text)
            # Remove code block markers
            text = re.sub(r"```[\w]*\n", "", text)
            text = re.sub(r"```", "", text)
            # Remove inline code
            text = re.sub(r"`([^`]+)`", r"\1", text)
            # Remove links, keep text
            text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
            # Remove images
            text = re.sub(r"!\[([^\]]*)\]\([^)]+\)", r"", text)
            # Remove horizontal rules
            text = re.sub(r"^[-*_]{3,}\s*$", "", text, flags=re.MULTILINE)
            # Remove blockquote markers
            text = re.sub(r"^>\s?", "", text, flags=re.MULTILINE)
            # Clean up list markers
            text = re.sub(r"^\s*[-*+]\s+", "", text, flags=re.MULTILINE)
            text = re.sub(r"^\s*\d+\.\s+", "", text, flags=re.MULTILINE)
            return text.strip()
        except UnicodeDecodeError as e:
            raise ParseError(f"Failed to decode Markdown file: {e}") from e
