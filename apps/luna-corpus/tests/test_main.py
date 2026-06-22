"""Tests for FastAPI application startup configuration."""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.core.config import AppEnv, Settings


def test_app_uses_configured_cors_origins():
    settings = Settings(
        app_env=AppEnv.DEVELOPMENT,
        cors_allow_origins="http://localhost:3000",
    )

    with patch("app.main.settings", settings):
        from app.main import create_app

        app = create_app()
        client = TestClient(app)
        response = client.options(
            "/",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "GET",
            },
        )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"


@pytest.mark.asyncio
async def test_lifespan_skips_init_db_when_auto_create_tables_disabled():
    settings = Settings(app_env=AppEnv.DEVELOPMENT, auto_create_tables=False)

    with patch("app.main.settings", settings), patch("app.main.init_db") as init_db:
        from app.main import create_app

        app = create_app()
        async with app.router.lifespan_context(app):
            pass

    init_db.assert_not_called()


@pytest.mark.asyncio
async def test_lifespan_calls_init_db_when_auto_create_tables_enabled():
    settings = Settings(app_env=AppEnv.DEVELOPMENT, auto_create_tables=True)

    with patch("app.main.settings", settings), patch("app.main.init_db") as init_db:
        from app.main import create_app

        app = create_app()
        async with app.router.lifespan_context(app):
            pass

    init_db.assert_called_once_with()
