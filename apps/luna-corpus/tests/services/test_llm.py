"""Tests for Ollama integration."""
from unittest.mock import MagicMock, patch

import pytest


def test_embed_text():
    """Test embedding a single text."""
    from app.services import llm

    mock_embeddings = MagicMock()
    mock_embeddings.embed_query.return_value = [0.1, 0.2, 0.3]

    with patch.object(llm, "get_embeddings_model", return_value=mock_embeddings):
        result = llm.embed_text("test text")
        assert result == [0.1, 0.2, 0.3]


def test_embed_texts():
    """Test embedding multiple texts."""
    from app.services import llm

    mock_embeddings = MagicMock()
    mock_embeddings.embed_documents.return_value = [
        [0.1, 0.2, 0.3],
        [0.4, 0.5, 0.6],
    ]

    with patch.object(llm, "get_embeddings_model", return_value=mock_embeddings):
        result = llm.embed_texts(["text1", "text2"])
        assert len(result) == 2
        assert result[0] == [0.1, 0.2, 0.3]


def test_generate_response_with_context():
    """Test generating response with context."""
    from app.services import llm

    mock_response = MagicMock()
    mock_response.content = "Test response"

    mock_chat = MagicMock()
    mock_chat.invoke.return_value = mock_response

    with patch.object(llm, "get_chat_model", return_value=mock_chat):
        result = llm.generate_response(
            prompt="What is Python?",
            context="Python is a programming language.",
        )

        assert result == "Test response"
        # Verify the prompt includes context
        call_args = mock_chat.invoke.call_args[0][0]
        assert "Context:" in call_args
        assert "Python is a programming language" in call_args


def test_check_ollama_health_success():
    """Test Ollama health check when healthy."""
    from app.services import llm

    with patch("httpx.get") as mock_get:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_get.return_value = mock_response

        result = llm.check_ollama_health()
        assert result is True


def test_check_ollama_health_failure():
    """Test Ollama health check when unreachable."""
    from app.services import llm

    with patch("httpx.get") as mock_get:
        mock_get.side_effect = Exception("Connection refused")

        result = llm.check_ollama_health()
        assert result is False


def test_check_deepseek_health_with_key():
    """Test DeepSeek health check when API key is configured."""
    from app.core.config import Settings
    from app.services import llm

    mock_settings = Settings(deepseek_api_key="test-key-123")

    with patch.object(llm, "settings", mock_settings):
        result = llm.check_deepseek_health()
        assert result is True


def test_check_deepseek_health_without_key():
    """Test DeepSeek health check when API key is not configured."""
    from app.core.config import Settings
    from app.services import llm

    mock_settings = Settings(deepseek_api_key="")

    with patch.object(llm, "settings", mock_settings):
        result = llm.check_deepseek_health()
        assert result is False


def test_get_provider_status():
    """Test getting provider status."""
    from app.core.config import LLMProvider, Settings
    from app.services import llm

    mock_settings = Settings(
        llm_provider=LLMProvider.OLLAMA,
        deepseek_api_key="test-key",
        ollama_base_url="http://localhost:11434",
        ollama_model="llama3.1",
        ollama_embed_model="nomic-embed-text",
        deepseek_model="deepseek-chat",
    )

    with patch.object(llm, "settings", mock_settings):
        with patch.object(llm, "check_ollama_health", return_value=True):
            status = llm.get_provider_status()

            assert status["current_provider"] == "ollama"
            assert status["ollama"]["available"] is True
            assert status["deepseek"]["configured"] is True
