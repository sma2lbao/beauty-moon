"""End-to-end integration tests."""
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def mock_all_services():
    """Mock all external services."""
    with patch("app.db.database.engine") as mock_engine, \
         patch("app.db.vectorstore.get_vector_store") as mock_chroma, \
         patch("app.services.llm.get_embeddings_model") as mock_embed, \
         patch("app.services.llm.get_chat_model") as mock_chat:

        mock_engine.return_value = MagicMock()
        mock_chroma.return_value = MagicMock()

        yield {
            "engine": mock_engine,
            "chroma": mock_chroma,
            "embed": mock_embed,
            "chat": mock_chat,
        }


def test_api_routes_import():
    """Test that API routes can be imported."""
    from app.api.routes import router

    assert router is not None
    assert len(router.routes) > 0


def test_main_app_import():
    """Test that main app can be imported."""
    from app.main import app

    assert app is not None
    assert app.title == "Luna-Corpus API"


def test_config_settings():
    """Test configuration loading."""
    from app.core.config import Settings

    settings = Settings()
    assert settings.ollama_model == "llama3.1"
    assert settings.ollama_embed_model == "nomic-embed-text"
    assert settings.retrieval_top_k == 5
