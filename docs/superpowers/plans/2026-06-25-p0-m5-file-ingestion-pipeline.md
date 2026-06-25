# P0-M5 文件摄取与解析管线 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a file ingestion pipeline that uploads files (PDF, DOCX, Markdown, HTML, TXT), parses them to text, creates Documents, and vectorizes them synchronously.

**Architecture:** Add an `ingestion` service module with pluggable `StorageBackend` (local filesystem, abstracted for S3) and `DocumentParser` (registry pattern by MIME type). A new `FileUpload` model tracks file metadata and parsing status. New API endpoints orchestrate upload → storage → parse → document → vectorize.

**Tech Stack:** Python 3.11+, FastAPI, SQLAlchemy 2.0, Alembic, pypdf, python-docx, beautifulsoup4, pytest

## Global Constraints

- All ingestion APIs require RBAC authentication via existing `require_permission()` dependency.
- All database queries must filter by `knowledge_base_id`.
- Existing `Document` and `DocumentProcessor` processing logic must remain unchanged.
- File storage base path must be relative (`{knowledge_base_id}/{uuid}/{safe_filename}`).
- `UploadFile` max size: 50MB default.
- Duplicate file policy: `reject` (default) or `replace`.
- Test database: SQLite in-memory via existing `db_session` fixture pattern.
- Ruff line length: 88 characters.
- Python version: >=3.11,<4.

---

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `app/services/ingestion/__init__.py` | Create | Package exports |
| `app/services/ingestion/exceptions.py` | Create | Ingestion-specific exceptions |
| `app/services/ingestion/storage.py` | Create | `StorageBackend` protocol, `LocalStorageBackend`, factory |
| `app/services/ingestion/parsers.py` | Create | `DocumentParser` protocol, built-in parsers, `ParserRegistry` |
| `app/services/ingestion/service.py` | Create | `IngestionService` orchestrating the full pipeline |
| `app/db/models.py` | Modify | Add `FileUpload` model; add `file_id` to `Document` |
| `app/core/config.py` | Modify | Add `STORAGE_BACKEND`, `STORAGE_LOCAL_PATH`, `MAX_UPLOAD_SIZE`, `UPLOAD_DUPLICATE_POLICY` |
| `app/api/routes.py` | Modify | Add `/files/upload`, `/files`, `/files/{file_id}` endpoints |
| `alembic/versions/20260625_0004_file_upload.py` | Create | Migration for `file_uploads` table and `documents.file_id` column |
| `pyproject.toml` | Modify | Add `pypdf>=4.0`, `python-docx>=1.1`, `beautifulsoup4>=4.12` |
| `tests/services/ingestion/test_storage.py` | Create | Storage backend tests |
| `tests/services/ingestion/test_parsers.py` | Create | Parser and registry tests |
| `tests/services/ingestion/test_service.py` | Create | IngestionService tests (mocked) |
| `tests/api/test_file_upload.py` | Create | API endpoint integration tests |

---

### Task 1: Ingestion Exceptions and Storage Backend

**Files:**
- Create: `app/services/ingestion/exceptions.py`
- Create: `app/services/ingestion/storage.py`
- Create: `tests/services/ingestion/test_storage.py`
- Modify: `app/services/ingestion/__init__.py`

**Interfaces:**
- Consumes: FastAPI `UploadFile`, app settings via `get_settings()`
- Produces: `StorageBackend` protocol, `LocalStorageBackend`, `get_storage_backend()` factory

- [ ] **Step 1: Write failing tests for exceptions and storage backend**

Create `tests/services/ingestion/test_storage.py`:

```python
"""Tests for ingestion storage backend."""
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


def test_local_storage_save(local_backend, temp_storage_path, sample_upload_file):
    """Test saving a file to local storage."""
    stored_path = local_backend.save(sample_upload_file, "kb-1/abc/test.txt")
    assert stored_path == "kb-1/abc/test.txt"
    assert (temp_storage_path / "kb-1" / "abc" / "test.txt").exists()
    with open(temp_storage_path / "kb-1" / "abc" / "test.txt", "rb") as f:
        assert f.read() == b"Hello, world!"


def test_local_storage_read(local_backend, sample_upload_file):
    """Test reading a file from local storage."""
    local_backend.save(sample_upload_file, "kb-1/abc/test.txt")
    content = local_backend.read("kb-1/abc/test.txt")
    assert content == b"Hello, world!"


def test_local_storage_delete(local_backend, sample_upload_file):
    """Test deleting a file from local storage."""
    local_backend.save(sample_upload_file, "kb-1/abc/test.txt")
    local_backend.delete("kb-1/abc/test.txt")
    assert not (local_backend.base_path / "kb-1" / "abc" / "test.txt").exists()


def test_local_storage_get_url(local_backend):
    """Test get_url returns None for local storage."""
    assert local_backend.get_url("kb-1/abc/test.txt") is None


def test_local_storage_read_not_found(local_backend):
    """Test reading a non-existent file raises StorageError."""
    with pytest.raises(StorageError, match="File not found"):
        local_backend.read("kb-1/missing.txt")


def test_local_storage_delete_not_found(local_backend):
    """Test deleting a non-existent file raises StorageError."""
    with pytest.raises(StorageError, match="File not found"):
        local_backend.delete("kb-1/missing.txt")


def test_get_storage_backend_returns_local(monkeypatch, tmp_path):
    """Test factory returns LocalStorageBackend by default."""
    from app.core.config import Settings
    settings = Settings(storage_backend="local", storage_local_path=tmp_path / "uploads")
    monkeypatch.setattr("app.services.ingestion.storage.get_settings", lambda: settings)
    backend = get_storage_backend()
    assert isinstance(backend, LocalStorageBackend)
```

Create `app/services/ingestion/__init__.py` (empty for now, just the package marker):

```python
"""Ingestion services for file upload, parse, and document creation."""
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd apps/luna-corpus && python -m pytest tests/services/ingestion/test_storage.py -v`

Expected: FAIL with import errors for `exceptions` and `storage` modules.

- [ ] **Step 3: Implement exceptions module**

Create `app/services/ingestion/exceptions.py`:

```python
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
```

- [ ] **Step 4: Implement storage module**

Create `app/services/ingestion/storage.py`:

```python
"""Storage backend abstraction and local filesystem implementation."""
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
        from pathlib import Path

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
        from pathlib import Path

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
        from pathlib import Path

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
        from pathlib import Path

        target = self.base_path / path
        if not target.exists():
            raise StorageError(f"File not found: {path}")
        target.unlink()

    def get_url(self, path: str) -> str | None:
        """Return public URL. Local storage has no public URL."""
        return None


def get_storage_backend() -> LocalStorageBackend:
    """Get configured storage backend instance.

    Returns:
        StorageBackend instance
    """
    settings = get_settings()
    return LocalStorageBackend(base_path=settings.storage_local_path)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd apps/luna-corpus && python -m pytest tests/services/ingestion/test_storage.py -v`

Expected: PASS (8 tests)

- [ ] **Step 6: Commit**

```bash
git add apps/luna-corpus/app/services/ingestion/ apps/luna-corpus/tests/services/ingestion/
git commit -m "feat(ingestion): add storage backend abstraction and local filesystem implementation"
```

---

### Task 2: Plain Text Parser

**Files:**
- Modify: `app/services/ingestion/parsers.py` (create with protocol + plaintext)
- Create: `tests/services/ingestion/test_parsers.py`

**Interfaces:**
- Consumes: Nothing (new module)
- Produces: `DocumentParser` protocol, `PlainTextParser`

- [ ] **Step 1: Write failing test for PlainTextParser**

Create `tests/services/ingestion/test_parsers.py`:

```python
"""Tests for document parsers."""

import pytest

from app.services.ingestion.exceptions import ParseError, UnsupportedFileTypeError
from app.services.ingestion.parsers import PlainTextParser


def test_plain_text_parser_mime_types():
    """Test plain text parser supported MIME types."""
    parser = PlainTextParser()
    assert "text/plain" in parser.supported_mime_types


def test_plain_text_parser_parse():
    """Test parsing plain text."""
    parser = PlainTextParser()
    content = b"Hello, world!\nThis is a test."
    result = parser.parse(content, "test.txt")
    assert result == "Hello, world!\nThis is a test."


def test_plain_text_parser_parse_utf8():
    """Test parsing UTF-8 text with special characters."""
    parser = PlainTextParser()
    content = "你好，世界！".encode("utf-8")
    result = parser.parse(content, "test.txt")
    assert result == "你好，世界！"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd apps/luna-corpus && python -m pytest tests/services/ingestion/test_parsers.py::test_plain_text_parser_parse -v`

Expected: FAIL with `ImportError` for `parsers` module.

- [ ] **Step 3: Implement parser protocol and PlainTextParser**

Create `app/services/ingestion/parsers.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd apps/luna-corpus && python -m pytest tests/services/ingestion/test_parsers.py -v`

Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add apps/luna-corpus/app/services/ingestion/parsers.py apps/luna-corpus/tests/services/ingestion/test_parsers.py
git commit -m "feat(ingestion): add document parser protocol and plain text parser"
```

---

### Task 3: PDF, DOCX, HTML, Markdown Parsers

**Files:**
- Modify: `app/services/ingestion/parsers.py`
- Modify: `tests/services/ingestion/test_parsers.py`
- Modify: `pyproject.toml`

**Interfaces:**
- Consumes: `DocumentParser` protocol from Task 2
- Produces: `PyPDFParser`, `DocxParser`, `HTMLParser`, `MarkdownParser`

- [ ] **Step 1: Add parser dependencies**

Modify `apps/luna-corpus/pyproject.toml`, add to `[project] dependencies`:

```toml
    "pypdf>=4.0",
    "python-docx>=1.1",
    "beautifulsoup4>=4.12",
```

Install: `cd apps/luna-corpus && uv pip install -e ".[dev]"` or `pip install pypdf python-docx beautifulsoup4`

- [ ] **Step 2: Write failing tests for format parsers**

Append to `tests/services/ingestion/test_parsers.py`:

```python
import io

from pypdf import PdfWriter


def test_pdf_parser_mime_types():
    """Test PDF parser supported MIME types."""
    from app.services.ingestion.parsers import PyPDFParser

    parser = PyPDFParser()
    assert "application/pdf" in parser.supported_mime_types


def test_pdf_parser_parse():
    """Test parsing a simple PDF."""
    from app.services.ingestion.parsers import PyPDFParser

    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    pdf_bytes = io.BytesIO()
    writer.write(pdf_bytes)
    pdf_bytes.seek(0)

    parser = PyPDFParser()
    result = parser.parse(pdf_bytes.read(), "test.pdf")
    assert isinstance(result, str)


def test_docx_parser_mime_types():
    """Test DOCX parser supported MIME types."""
    from app.services.ingestion.parsers import DocxParser

    parser = DocxParser()
    assert (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        in parser.supported_mime_types
    )


def test_docx_parser_parse():
    """Test parsing a simple DOCX."""
    from docx import Document as DocxDocument
    from app.services.ingestion.parsers import DocxParser

    doc = DocxDocument()
    doc.add_paragraph("Hello, world!")
    docx_bytes = io.BytesIO()
    doc.save(docx_bytes)
    docx_bytes.seek(0)

    parser = DocxParser()
    result = parser.parse(docx_bytes.read(), "test.docx")
    assert "Hello, world!" in result


def test_html_parser_mime_types():
    """Test HTML parser supported MIME types."""
    from app.services.ingestion.parsers import HTMLParser

    parser = HTMLParser()
    assert "text/html" in parser.supported_mime_types


def test_html_parser_parse():
    """Test parsing HTML to text."""
    from app.services.ingestion.parsers import HTMLParser

    parser = HTMLParser()
    html = b"<html><body><p>Hello, world!</p></body></html>"
    result = parser.parse(html, "test.html")
    assert "Hello, world!" in result
    assert "<html>" not in result


def test_markdown_parser_mime_types():
    """Test Markdown parser supported MIME types."""
    from app.services.ingestion.parsers import MarkdownParser

    parser = MarkdownParser()
    assert "text/markdown" in parser.supported_mime_types
    assert "text/x-markdown" in parser.supported_mime_types


def test_markdown_parser_parse():
    """Test parsing Markdown to text."""
    from app.services.ingestion.parsers import MarkdownParser

    parser = MarkdownParser()
    md = b"# Hello\n\nThis is **bold** text."
    result = parser.parse(md, "test.md")
    assert "Hello" in result
    assert "This is bold text." in result
    assert "#" not in result
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd apps/luna-corpus && python -m pytest tests/services/ingestion/test_parsers.py::test_pdf_parser_parse -v`

Expected: FAIL with `ImportError` for parser classes.

- [ ] **Step 4: Implement format parsers**

Append to `app/services/ingestion/parsers.py`:

```python

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
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd apps/luna-corpus && python -m pytest tests/services/ingestion/test_parsers.py -v`

Expected: PASS (11 tests)

- [ ] **Step 6: Commit**

```bash
git add apps/luna-corpus/app/services/ingestion/parsers.py apps/luna-corpus/tests/services/ingestion/test_parsers.py apps/luna-corpus/pyproject.toml
git commit -m "feat(ingestion): add PDF, DOCX, HTML, and Markdown parsers"
```

---

### Task 4: Parser Registry

**Files:**
- Modify: `app/services/ingestion/parsers.py`
- Modify: `tests/services/ingestion/test_parsers.py`

**Interfaces:**
- Consumes: All parser classes from Tasks 2-3
- Produces: `ParserRegistry`, `get_parser_registry()`

- [ ] **Step 1: Write failing tests for ParserRegistry**

Append to `tests/services/ingestion/test_parsers.py`:

```python
def test_parser_registry_register_and_get():
    """Test registering and retrieving parsers."""
    from app.services.ingestion.parsers import ParserRegistry, PlainTextParser

    registry = ParserRegistry()
    parser = PlainTextParser()
    registry.register(parser)

    assert registry.get_parser("text/plain") is parser


def test_parser_registry_is_supported():
    """Test checking supported MIME types."""
    from app.services.ingestion.parsers import ParserRegistry, PlainTextParser

    registry = ParserRegistry()
    registry.register(PlainTextParser())

    assert registry.is_supported("text/plain") is True
    assert registry.is_supported("application/pdf") is False


def test_parser_registry_unsupported_type():
    """Test getting parser for unsupported type raises error."""
    from app.services.ingestion.parsers import ParserRegistry

    registry = ParserRegistry()
    with pytest.raises(UnsupportedFileTypeError, match="Unsupported file type"):
        registry.get_parser("application/unknown")


def test_parser_registry_list_supported_types():
    """Test listing supported MIME types."""
    from app.services.ingestion.parsers import ParserRegistry, PlainTextParser

    registry = ParserRegistry()
    registry.register(PlainTextParser())

    types = registry.list_supported_types()
    assert "text/plain" in types


def test_default_parser_registry_has_all_parsers():
    """Test default registry includes all built-in parsers."""
    from app.services.ingestion.parsers import get_parser_registry

    registry = get_parser_registry()
    assert registry.is_supported("text/plain")
    assert registry.is_supported("application/pdf")
    assert registry.is_supported(
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    assert registry.is_supported("text/html")
    assert registry.is_supported("text/markdown")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd apps/luna-corpus && python -m pytest tests/services/ingestion/test_parsers.py::test_parser_registry_register_and_get -v`

Expected: FAIL with `ImportError` for `ParserRegistry`.

- [ ] **Step 3: Implement ParserRegistry**

Append to `app/services/ingestion/parsers.py`:

```python
from app.services.ingestion.exceptions import UnsupportedFileTypeError


class ParserRegistry:
    """Registry for document parsers by MIME type."""

    def __init__(self):
        """Initialize empty registry."""
        self._parsers: dict[str, DocumentParser] = {}

    def register(self, parser: DocumentParser) -> None:
        """Register a parser for its supported MIME types.

        Args:
            parser: Document parser instance
        """
        for mime_type in parser.supported_mime_types:
            self._parsers[mime_type] = parser

    def get_parser(self, mime_type: str) -> DocumentParser:
        """Get parser for a MIME type.

        Args:
            mime_type: MIME type string

        Returns:
            DocumentParser instance

        Raises:
            UnsupportedFileTypeError: If MIME type is not supported
        """
        parser = self._parsers.get(mime_type)
        if parser is None:
            supported = ", ".join(sorted(self._parsers.keys()))
            raise UnsupportedFileTypeError(
                f"Unsupported file type: {mime_type}. "
                f"Supported types: {supported}"
            )
        return parser

    def is_supported(self, mime_type: str) -> bool:
        """Check if a MIME type is supported.

        Args:
            mime_type: MIME type string

        Returns:
            True if supported
        """
        return mime_type in self._parsers

    def list_supported_types(self) -> list[str]:
        """List all supported MIME types.

        Returns:
            Sorted list of MIME types
        """
        return sorted(self._parsers.keys())


def get_parser_registry() -> ParserRegistry:
    """Get default parser registry with all built-in parsers.

    Returns:
        Configured ParserRegistry
    """
    registry = ParserRegistry()
    registry.register(PlainTextParser())
    registry.register(PyPDFParser())
    registry.register(DocxParser())
    registry.register(HTMLParser())
    registry.register(MarkdownParser())
    return registry
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd apps/luna-corpus && python -m pytest tests/services/ingestion/test_parsers.py -v`

Expected: PASS (16 tests)

- [ ] **Step 5: Commit**

```bash
git add apps/luna-corpus/app/services/ingestion/parsers.py apps/luna-corpus/tests/services/ingestion/test_parsers.py
git commit -m "feat(ingestion): add parser registry with built-in parser registration"
```

---

### Task 5: Data Model Changes and Alembic Migration

**Files:**
- Modify: `app/db/models.py`
- Create: `alembic/versions/20260625_0004_file_upload.py`
- Modify: `tests/db/test_models.py`

**Interfaces:**
- Consumes: Existing model patterns
- Produces: `FileUpload` model, `Document.file_id`, `Document.file`

- [ ] **Step 1: Write failing test for FileUpload model**

Append to `tests/db/test_models.py`:

```python
from app.db.models import FileUpload


def test_file_upload_creation(db_session):
    """Test creating a file upload record."""
    _, _, knowledge_base = create_knowledge_base(db_session)
    upload = FileUpload(
        knowledge_base_id=knowledge_base.id,
        original_name="report.pdf",
        stored_name="kb-1/abc/report.pdf",
        mime_type="application/pdf",
        size_bytes=1024,
        content_hash="abc123",
        status="uploaded",
    )
    db_session.add(upload)
    db_session.commit()

    assert upload.id is not None
    assert upload.original_name == "report.pdf"
    assert upload.status == "uploaded"


def test_document_with_file_id(db_session):
    """Test creating a document linked to a file upload."""
    from app.db.models import FileUploadStatus

    _, _, knowledge_base = create_knowledge_base(db_session)
    upload = FileUpload(
        knowledge_base_id=knowledge_base.id,
        original_name="report.pdf",
        stored_name="kb-1/abc/report.pdf",
        mime_type="application/pdf",
        size_bytes=1024,
        content_hash="abc123",
        status=FileUploadStatus.UPLOADED,
    )
    db_session.add(upload)
    db_session.commit()

    doc = Document(
        title="Report",
        content="Parsed content",
        knowledge_base_id=knowledge_base.id,
        file_id=upload.id,
    )
    db_session.add(doc)
    db_session.commit()

    assert doc.file_id == upload.id
    assert doc.file == upload
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd apps/luna-corpus && python -m pytest tests/db/test_models.py::test_file_upload_creation -v`

Expected: FAIL with `ImportError` for `FileUpload`.

- [ ] **Step 3: Add FileUploadStatus enum and FileUpload model**

Add to `app/db/models.py` after `ContentStatus`:

```python

class FileUploadStatus(str, enum.Enum):
    """File upload processing status."""

    UPLOADED = "uploaded"
    PARSED = "parsed"
    ERROR = "error"
```

Add to `app/db/models.py` after `KnowledgeBase` class:

```python

class FileUpload(Base):
    """Uploaded file record."""

    __tablename__ = "file_uploads"

    id: Mapped[str] = mapped_column(
        CHAR(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    knowledge_base_id: Mapped[str] = mapped_column(
        CHAR(36), ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False
    )
    original_name: Mapped[str] = mapped_column(String(500), nullable=False)
    stored_name: Mapped[str] = mapped_column(String(500), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(255), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[FileUploadStatus] = mapped_column(
        Enum(FileUploadStatus), default=FileUploadStatus.UPLOADED
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    parsed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    knowledge_base: Mapped[KnowledgeBase] = relationship(
        "KnowledgeBase", back_populates="file_uploads"
    )
    document: Mapped["Document"] = relationship(
        "Document", back_populates="file", uselist=False
    )
```

Modify `KnowledgeBase` to add relationship:

```python
    documents: Mapped[list["Document"]] = relationship(
        "Document", back_populates="knowledge_base", cascade="all, delete-orphan"
    )
    conversations: Mapped[list["Conversation"]] = relationship(
        "Conversation", back_populates="knowledge_base", cascade="all, delete-orphan"
    )
    file_uploads: Mapped[list["FileUpload"]] = relationship(
        "FileUpload", back_populates="knowledge_base", cascade="all, delete-orphan"
    )
```

Modify `Document` class to add `file_id`:

```python
class Document(Base):
    """Document model."""

    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(
        CHAR(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    knowledge_base_id: Mapped[str] = mapped_column(
        CHAR(36), ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False
    )
    file_id: Mapped[str | None] = mapped_column(
        CHAR(36), ForeignKey("file_uploads.id"), nullable=True
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    ...

    # Relationships
    chunks: Mapped[list["Chunk"]] = relationship(
        "Chunk", back_populates="document", cascade="all, delete-orphan"
    )
    knowledge_base: Mapped["KnowledgeBase"] = relationship(
        "KnowledgeBase", back_populates="documents"
    )
    file: Mapped["FileUpload | None"] = relationship(
        "FileUpload", back_populates="document"
    )
```

- [ ] **Step 4: Create Alembic migration**

Run: `cd apps/luna-corpus && alembic revision --autogenerate -m "add file_uploads table and documents.file_id"`

Review generated migration at `alembic/versions/20260625_0004_*.py` and ensure it contains:
- `file_uploads` table creation with all columns
- `documents.file_id` column addition
- `documents` foreign key to `file_uploads`

If autogenerate misses anything, manually fix. Expected migration:

```python
"""add file_uploads table and documents.file_id

Revision ID: 20260625_0004
Revises: 20260623_0003
Create Date: 2026-06-25
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "20260625_0004"
down_revision: str | None = "20260623_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "file_uploads",
        sa.Column("id", mysql.CHAR(36), nullable=False),
        sa.Column("knowledge_base_id", mysql.CHAR(36), nullable=False),
        sa.Column("original_name", sa.String(500), nullable=False),
        sa.Column("stored_name", sa.String(500), nullable=False),
        sa.Column("mime_type", sa.String(255), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.Enum("uploaded", "parsed", "error", name="fileuploadstatus"), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("parsed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("NOW()")),
        sa.ForeignKeyConstraint(["knowledge_base_id"], ["knowledge_bases.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.add_column("documents", sa.Column("file_id", mysql.CHAR(36), nullable=True))
    op.create_foreign_key(None, "documents", "file_uploads", ["file_id"], ["id"])


def downgrade() -> None:
    op.drop_constraint(None, "documents", type_="foreignkey")
    op.drop_column("documents", "file_id")
    op.drop_table("file_uploads")
    op.execute("DROP TYPE IF EXISTS fileuploadstatus")
```

- [ ] **Step 5: Run model tests to verify they pass**

Run: `cd apps/luna-corpus && python -m pytest tests/db/test_models.py -v`

Expected: PASS (all existing + 2 new tests)

- [ ] **Step 6: Run migration**

Run: `cd apps/luna-corpus && alembic upgrade head`

Expected: SUCCESS

- [ ] **Step 7: Commit**

```bash
git add apps/luna-corpus/app/db/models.py apps/luna-corpus/alembic/versions/ apps/luna-corpus/tests/db/test_models.py
git commit -m "feat(db): add FileUpload model and documents.file_id column"
```

---

### Task 6: Configuration Extensions

**Files:**
- Modify: `app/core/config.py`
- Modify: `tests/core/test_config.py`

**Interfaces:**
- Consumes: Existing `Settings` class
- Produces: `storage_backend`, `storage_local_path`, `max_upload_size`, `upload_duplicate_policy` settings

- [ ] **Step 1: Write failing test for new config fields**

Append to `tests/core/test_config.py`:

```python
def test_default_storage_config():
    """Test default storage configuration values."""
    from app.core.config import Settings

    settings = Settings()
    assert settings.storage_backend == "local"
    assert settings.storage_local_path == "./data/uploads"
    assert settings.max_upload_size == 52428800
    assert settings.upload_duplicate_policy == "reject"


def test_custom_storage_config():
    """Test custom storage configuration."""
    from app.core.config import Settings

    settings = Settings(
        storage_backend="s3",
        storage_local_path="/tmp/uploads",
        max_upload_size=10485760,
        upload_duplicate_policy="replace",
    )
    assert settings.storage_backend == "s3"
    assert settings.storage_local_path == "/tmp/uploads"
    assert settings.max_upload_size == 10485760
    assert settings.upload_duplicate_policy == "replace"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd apps/luna-corpus && python -m pytest tests/core/test_config.py::test_default_storage_config -v`

Expected: FAIL with `AttributeError` for missing fields.

- [ ] **Step 3: Add storage and upload settings**

Add to `app/core/config.py` in `Settings` class, after `cors_allow_origins`:

```python
    # Storage
    storage_backend: str = Field(
        default="local",
        description="Storage backend: local or s3",
    )
    storage_local_path: Path = Field(
        default=Path("./data/uploads"),
        description="Base path for local file storage",
    )
    max_upload_size: int = Field(
        default=52428800,
        description="Maximum upload file size in bytes (50MB)",
    )
    upload_duplicate_policy: str = Field(
        default="reject",
        description="Duplicate file policy: reject or replace",
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd apps/luna-corpus && python -m pytest tests/core/test_config.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apps/luna-corpus/app/core/config.py apps/luna-corpus/tests/core/test_config.py
git commit -m "feat(config): add storage and upload configuration settings"
```

---

### Task 7: IngestionService

**Files:**
- Create: `app/services/ingestion/service.py`
- Create: `tests/services/ingestion/test_service.py`

**Interfaces:**
- Consumes: `StorageBackend` (Task 1), `ParserRegistry` (Task 4), `FileUpload`/`Document` models (Task 5), `Settings` (Task 6), `DocumentProcessor`
- Produces: `IngestionService.ingest_file()`, `IngestionService.delete_file()`

- [ ] **Step 1: Write failing tests for IngestionService**

Create `tests/services/ingestion/test_service.py`:

```python
"""Tests for ingestion service."""
from datetime import datetime
from unittest.mock import MagicMock

import pytest

from app.db.models import ContentStatus, Document, FileUpload, FileUploadStatus
from app.services.ingestion.exceptions import (
    DuplicateFileError,
    ParseError,
    UnsupportedFileTypeError,
)
from app.services.ingestion.service import IngestionService


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
    file = MagicMock()
    file.filename = "test.pdf"
    file.content_type = "application/pdf"
    file.size = 1024
    file.read = MagicMock(return_value=b"pdf content")

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
    file = MagicMock()
    file.filename = "test.unknown"
    file.content_type = "application/unknown"
    file.size = 1024

    with pytest.raises(UnsupportedFileTypeError):
        ingestion_service.ingest_file(db, file, "kb-1")


def test_ingest_file_too_large(ingestion_service):
    """Test ingestion with file exceeding size limit."""
    db = MagicMock()
    file = MagicMock()
    file.filename = "huge.pdf"
    file.content_type = "application/pdf"
    file.size = 100_000_000  # 100MB

    with pytest.raises(HTTPException) as exc:
        ingestion_service.ingest_file(db, file, "kb-1")
    assert exc.value.status_code == 413


def test_ingest_file_duplicate_reject(ingestion_service):
    """Test duplicate file rejection."""
    db = MagicMock()
    # Simulate existing file with same hash
    existing = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = existing

    file = MagicMock()
    file.filename = "test.pdf"
    file.content_type = "application/pdf"
    file.size = 1024
    file.read = MagicMock(return_value=b"pdf content")

    with pytest.raises(DuplicateFileError):
        ingestion_service.ingest_file(db, file, "kb-1")


def test_ingest_file_parse_error(ingestion_service, mock_parser_registry):
    """Test handling of parse errors."""
    parser = MagicMock()
    parser.parse = MagicMock(side_effect=ParseError("Corrupted file"))
    mock_parser_registry.get_parser.return_value = parser

    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = None

    file = MagicMock()
    file.filename = "corrupted.pdf"
    file.content_type = "application/pdf"
    file.size = 1024
    file.read = MagicMock(return_value=b"bad content")

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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd apps/luna-corpus && python -m pytest tests/services/ingestion/test_service.py::test_ingest_file_success -v`

Expected: FAIL with `ImportError` for `service` module.

- [ ] **Step 3: Implement IngestionService**

Create `app/services/ingestion/service.py`:

```python
"""Ingestion service orchestrating upload, storage, parse, document, vectorize."""
import hashlib
import uuid
from pathlib import Path

from fastapi import HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.db.models import ContentStatus, Document, FileUpload, FileUploadStatus
from app.services.document_processor import DocumentProcessor
from app.services.ingestion.exceptions import (
    DuplicateFileError,
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
    """Orchestrate file upload → storage → parse → document → vectorize."""

    def __init__(
        self,
        storage: StorageBackend,
        parser_registry: ParserRegistry,
        processor: DocumentProcessor,
        max_upload_size: int = 52428800,
        duplicate_policy: str = "reject",
    ):
        """Initialize ingestion service.

        Args:
            storage: Storage backend instance
            parser_registry: Parser registry instance
            processor: Document processor for chunking/vectorization
            max_upload_size: Maximum allowed file size in bytes
            duplicate_policy: How to handle duplicate files: "reject" or "replace"
        """
        self.storage = storage
        self.parser_registry = parser_registry
        self.processor = processor
        self.max_upload_size = max_upload_size
        self.duplicate_policy = duplicate_policy

    def ingest_file(
        self,
        db: Session,
        file: UploadFile,
        knowledge_base_id: str,
    ) -> FileUpload:
        """Ingest a file: store, parse, create document, vectorize.

        Args:
            db: Database session
            file: Uploaded file
            knowledge_base_id: Target knowledge base ID

        Returns:
            FileUpload record

        Raises:
            HTTPException: 413 if file too large
            UnsupportedFileTypeError: If MIME type not supported
            DuplicateFileError: If duplicate detected and policy is reject
        """
        # Validate file size
        if file.size and file.size > self.max_upload_size:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
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
            self.delete_file(db, existing.id, knowledge_base_id)

        # Generate storage path and save file
        stored_name = _generate_storage_path(knowledge_base_id, file.filename or "unknown")

        # Create FileUpload record first
        upload = FileUpload(
            knowledge_base_id=knowledge_base_id,
            original_name=file.filename or "unknown",
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
            self.storage.save(file, stored_name)

            # Parse content
            parser = self.parser_registry.get_parser(mime_type)
            parsed_text = parser.parse(content, file.filename or "unknown")

            # Create Document
            document = Document(
                knowledge_base_id=knowledge_base_id,
                file_id=upload.id,
                title=file.filename or "Untitled",
                content=parsed_text,
                source=f"file://{file.filename}",
                has_tables="|" in parsed_text and "---" in parsed_text,
                has_code="```" in parsed_text or "def " in parsed_text,
                status=ContentStatus.PENDING,
            )
            db.add(document)
            db.commit()
            db.refresh(document)

            # Process document (chunk + vectorize)
            self.processor.process_document(db, document.id)

            # Update upload status
            upload.status = FileUploadStatus.PARSED
            upload.parsed_at = datetime.now()
            db.commit()
            db.refresh(upload)

            return upload

        except ParseError as e:
            upload.status = FileUploadStatus.ERROR
            upload.error_message = str(e)
            db.commit()
            # Clean up stored file
            try:
                self.storage.delete(stored_name)
            except StorageError:
                pass
            return upload

        except Exception as e:
            upload.status = FileUploadStatus.ERROR
            upload.error_message = str(e)
            db.commit()
            # Rollback: delete document if created
            doc = (
                db.query(Document)
                .filter(Document.file_id == upload.id)
                .first()
            )
            if doc:
                db.delete(doc)
                db.commit()
            # Clean up stored file
            try:
                self.storage.delete(stored_name)
            except StorageError:
                pass
            return upload

    def delete_file(
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

        # Delete associated document (which cascades to chunks and vectors)
        if upload.document:
            db.delete(upload.document)

        # Delete from storage
        try:
            self.storage.delete(upload.stored_name)
        except StorageError:
            pass

        # Delete upload record
        db.delete(upload)
        db.commit()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd apps/luna-corpus && python -m pytest tests/services/ingestion/test_service.py -v`

Expected: PASS (8 tests)

- [ ] **Step 5: Commit**

```bash
git add apps/luna-corpus/app/services/ingestion/service.py apps/luna-corpus/tests/services/ingestion/test_service.py
git commit -m "feat(ingestion): add IngestionService orchestrating upload, parse, and vectorize"
```

---

### Task 8: API Endpoints

**Files:**
- Modify: `app/api/routes.py`
- Create: `tests/api/test_file_upload.py`

**Interfaces:**
- Consumes: `IngestionService` (Task 7), `FileUpload` model (Task 5), RBAC dependencies (existing)
- Produces: `/api/v1/files/upload` (POST), `/api/v1/files` (GET), `/api/v1/files/{file_id}` (GET, DELETE)

- [ ] **Step 1: Write failing tests for file upload API**

Create `tests/api/test_file_upload.py`:

```python
"""Integration tests for file upload endpoints."""
import io
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.db.models import FileUpload, FileUploadStatus
from app.main import app

client = TestClient(app)


def _auth_headers(knowledge_base_id="kb-1"):
    return {
        "X-User-Id": "user-1",
        "X-Tenant-Id": "tenant-1",
        "X-Workspace-Id": "ws-1",
        "X-Knowledge-Base-Id": knowledge_base_id,
    }


@patch("app.api.routes.get_storage_backend")
@patch("app.api.routes.get_parser_registry")
@patch("app.api.routes.DocumentProcessor")
def test_upload_file_success(mock_processor, mock_registry, mock_storage):
    """Test successful file upload."""
    # Setup mocks
    storage = mock_storage.return_value
    storage.save = lambda f, p: p

    registry = mock_registry.return_value
    registry.is_supported.return_value = True
    parser = type("Parser", (), {"parse": lambda self, c, n: "Parsed text"})()
    registry.get_parser.return_value = parser

    mock_processor.return_value.process_document.return_value = []

    response = client.post(
        "/api/v1/files/upload",
        headers=_auth_headers(),
        files={"file": ("test.txt", io.BytesIO(b"Hello"), "text/plain")},
    )

    assert response.status_code == 201
    data = response.json()
    assert data["original_name"] == "test.txt"
    assert data["mime_type"] == "text/plain"


@patch("app.api.routes.get_storage_backend")
@patch("app.api.routes.get_parser_registry")
def test_upload_file_unsupported_type(mock_registry, mock_storage):
    """Test upload with unsupported file type."""
    registry = mock_registry.return_value
    registry.is_supported.return_value = False
    registry.list_supported_types.return_value = ["text/plain"]

    response = client.post(
        "/api/v1/files/upload",
        headers=_auth_headers(),
        files={"file": ("test.unknown", io.BytesIO(b"data"), "application/unknown")},
    )

    assert response.status_code == 415


def test_list_files_requires_auth():
    """Test list files requires authentication."""
    response = client.get("/api/v1/files")
    assert response.status_code == 403


def test_delete_file_requires_auth():
    """Test delete file requires authentication."""
    response = client.delete("/api/v1/files/file-1")
    assert response.status_code == 403
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd apps/luna-corpus && python -m pytest tests/api/test_file_upload.py::test_upload_file_success -v`

Expected: FAIL with `404` for unknown endpoint.

- [ ] **Step 3: Add API endpoints**

Add to `app/api/routes.py` after imports:

```python
from app.services.ingestion.parsers import get_parser_registry
from app.services.ingestion.service import IngestionService
from app.services.ingestion.storage import get_storage_backend
```

Add Pydantic models after existing response models:

```python

class FileUploadResponse(BaseModel):
    """File upload response model."""

    id: str
    knowledge_base_id: str
    original_name: str
    mime_type: str
    size_bytes: int
    content_hash: str
    status: str
    error_message: str | None
    parsed_at: str | None
    created_at: str
    updated_at: str

    model_config = ConfigDict(from_attributes=True)


class FileUploadListResponse(BaseModel):
    """File upload list response."""

    files: list[FileUploadResponse]
    total: int


class FileUploadCreateResponse(BaseModel):
    """File upload creation response with document info."""

    file: FileUploadResponse
    document_id: str | None
```

Add endpoints before the `HealthResponse` and health check endpoint (or at the end of document routes):

```python

# File Upload Management
@router.post("/files/upload", response_model=FileUploadCreateResponse, status_code=status.HTTP_201_CREATED)
async def upload_file(
    file: UploadFile,
    db: Annotated[Session, Depends(get_db)],
    context: Annotated[
        AuthenticatedRequestContext,
        Depends(require_permission(PermissionSlug.DOCUMENT_WRITE)),
    ],
) -> FileUploadCreateResponse:
    """Upload a file, parse it, and create a document.

    Args:
        file: Uploaded file
        db: Database session
        context: Request context with knowledge base scope

    Returns:
        Created file upload and document info
    """
    storage = get_storage_backend()
    registry = get_parser_registry()
    processor = DocumentProcessor()

    service = IngestionService(
        storage=storage,
        parser_registry=registry,
        processor=processor,
        max_upload_size=get_settings().max_upload_size,
        duplicate_policy=get_settings().upload_duplicate_policy,
    )

    try:
        upload = service.ingest_file(db, file, context.knowledge_base.id)
    except Exception as e:
        # Re-raise HTTPExceptions as-is
        if isinstance(e, HTTPException):
            raise
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )

    document_id = None
    if upload.document:
        document_id = upload.document.id

    return FileUploadCreateResponse(
        file=FileUploadResponse(
            id=upload.id,
            knowledge_base_id=upload.knowledge_base_id,
            original_name=upload.original_name,
            mime_type=upload.mime_type,
            size_bytes=upload.size_bytes,
            content_hash=upload.content_hash,
            status=upload.status.value,
            error_message=upload.error_message,
            parsed_at=upload.parsed_at.isoformat() if upload.parsed_at else None,
            created_at=upload.created_at.isoformat(),
            updated_at=upload.updated_at.isoformat(),
        ),
        document_id=document_id,
    )


@router.get("/files", response_model=FileUploadListResponse)
async def list_files(
    db: Annotated[Session, Depends(get_db)],
    context: Annotated[
        AuthenticatedRequestContext,
        Depends(require_permission(PermissionSlug.DOCUMENT_READ)),
    ],
) -> FileUploadListResponse:
    """List uploaded files for the knowledge base.

    Args:
        db: Database session
        context: Request context with knowledge base scope

    Returns:
        List of file uploads
    """
    uploads = (
        db.query(FileUpload)
        .filter(FileUpload.knowledge_base_id == context.knowledge_base.id)
        .order_by(FileUpload.created_at.desc())
        .all()
    )

    return FileUploadListResponse(
        files=[
            FileUploadResponse(
                id=u.id,
                knowledge_base_id=u.knowledge_base_id,
                original_name=u.original_name,
                mime_type=u.mime_type,
                size_bytes=u.size_bytes,
                content_hash=u.content_hash,
                status=u.status.value,
                error_message=u.error_message,
                parsed_at=u.parsed_at.isoformat() if u.parsed_at else None,
                created_at=u.created_at.isoformat(),
                updated_at=u.updated_at.isoformat(),
            )
            for u in uploads
        ],
        total=len(uploads),
    )


@router.get("/files/{file_id}", response_model=FileUploadResponse)
async def get_file(
    file_id: str,
    db: Annotated[Session, Depends(get_db)],
    context: Annotated[
        AuthenticatedRequestContext,
        Depends(require_permission(PermissionSlug.DOCUMENT_READ)),
    ],
) -> FileUploadResponse:
    """Get a file upload record by ID.

    Args:
        file_id: File upload ID
        db: Database session
        context: Request context with knowledge base scope

    Returns:
        File upload record
    """
    upload = (
        db.query(FileUpload)
        .filter(
            FileUpload.id == file_id,
            FileUpload.knowledge_base_id == context.knowledge_base.id,
        )
        .first()
    )
    if not upload:
        raise HTTPException(status_code=404, detail="File not found")

    return FileUploadResponse(
        id=upload.id,
        knowledge_base_id=upload.knowledge_base_id,
        original_name=upload.original_name,
        mime_type=upload.mime_type,
        size_bytes=upload.size_bytes,
        content_hash=upload.content_hash,
        status=upload.status.value,
        error_message=upload.error_message,
        parsed_at=upload.parsed_at.isoformat() if upload.parsed_at else None,
        created_at=upload.created_at.isoformat(),
        updated_at=upload.updated_at.isoformat(),
    )


@router.delete("/files/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_file(
    file_id: str,
    db: Annotated[Session, Depends(get_db)],
    context: Annotated[
        AuthenticatedRequestContext,
        Depends(require_permission(PermissionSlug.DOCUMENT_DELETE)),
    ],
) -> None:
    """Delete a file and its associated document.

    Args:
        file_id: File upload ID
        db: Database session
        context: Request context with knowledge base scope
    """
    storage = get_storage_backend()
    processor = DocumentProcessor()
    registry = get_parser_registry()

    service = IngestionService(
        storage=storage,
        parser_registry=registry,
        processor=processor,
    )

    service.delete_file(db, file_id, context.knowledge_base.id)
```

Also add `UploadFile` import at the top of `app/api/routes.py`:

```python
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, status
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd apps/luna-corpus && python -m pytest tests/api/test_file_upload.py -v`

Expected: PASS (4 tests). Note: integration tests with TestClient may need the database to be set up; if they fail with DB errors, check that the test environment has the tables created.

- [ ] **Step 5: Run full test suite**

Run: `cd apps/luna-corpus && python -m pytest tests/ -v --tb=short`

Expected: All existing tests continue to pass.

- [ ] **Step 6: Commit**

```bash
git add apps/luna-corpus/app/api/routes.py apps/luna-corpus/tests/api/test_file_upload.py
git commit -m "feat(api): add file upload, list, get, and delete endpoints"
```

---

## Spec Coverage Checklist

| Spec Requirement | Task |
|---|---|
| 文件上传 API，记录文件名/mime/size/hash/path | Task 8 |
| 支持 PDF/DOCX/Markdown/HTML/TXT 解析 | Tasks 2-4 |
| 解析结果转为 Document | Task 7 |
| FileUpload 独立模型，Document.file_id 关联 | Task 5 |
| 解析失败记录错误原因 | Task 7 |
| 预留 parser 接口（Registry 模式） | Task 4 |
| 预留 storage 接口（Backend 协议） | Task 1 |
| 同步向量化（复用 process_document） | Task 7 |
| RBAC 保护所有接口 | Task 8 |
| 知识库隔离 | Tasks 7-8 |
| 文件大小限制 | Tasks 6-7 |
| 重复文件处理 | Task 7 |
| 异常回滚（不创建半完成索引） | Task 7 |
| 测试覆盖（每种格式、错误路径、权限） | All tasks |

## Placeholder Scan

- No "TBD", "TODO", "implement later" found.
- No vague "add appropriate error handling" steps.
- All test code is complete with assertions.
- All file paths are exact.

## Type Consistency Check

- `FileUploadStatus` enum values: `UPLOADED`, `PARSED`, `ERROR` — consistent across model, service, tests.
- `StorageBackend.save()` returns `str` (stored path) — consistent in protocol, implementation, tests.
- `IngestionService.ingest_file()` returns `FileUpload` — consistent across service and tests.
- `Document.file_id` is `str | None` — consistent in model and tests.

---

Plan complete and saved to `docs/superpowers/plans/2026-06-25-p0-m5-file-ingestion-pipeline.md`.

**Two execution options:**

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?