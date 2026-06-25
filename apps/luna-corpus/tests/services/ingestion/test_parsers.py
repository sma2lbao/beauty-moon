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
    content = "你好，世界！".encode()
    result = parser.parse(content, "test.txt")
    assert result == "你好，世界！"


def test_plain_text_parser_parse_invalid_encoding():
    """Test parsing raises ParseError for invalid UTF-8."""
    parser = PlainTextParser()
    # Invalid UTF-8 sequence
    content = b"\xff\xfe"
    with pytest.raises(ParseError):
        parser.parse(content, "test.txt")


def test_plain_text_parser_parse_empty():
    """Test parsing empty content."""
    parser = PlainTextParser()
    content = b""
    result = parser.parse(content, "test.txt")
    assert result == ""


def test_pdf_parser_mime_types():
    """Test PDF parser supported MIME types."""
    from app.services.ingestion.parsers import PyPDFParser

    parser = PyPDFParser()
    assert "application/pdf" in parser.supported_mime_types


def test_pdf_parser_parse():
    """Test parsing a simple PDF."""
    import io

    from pypdf import PdfWriter

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
    import io

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
