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
