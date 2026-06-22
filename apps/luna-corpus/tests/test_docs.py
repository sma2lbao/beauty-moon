"""Tests for project documentation and environment examples."""

from pathlib import Path

PROJECT_ROOT = Path(__file__).parents[1]


def test_env_example_documents_runtime_safety_settings():
    env_example = (PROJECT_ROOT / ".env.example").read_text()

    assert "APP_ENV=development" in env_example
    assert "AUTO_CREATE_TABLES=false" in env_example
    assert (
        "CORS_ALLOW_ORIGINS=http://localhost:3000,http://localhost:4200" in env_example
    )


def test_readme_documents_migration_commands():
    readme = (PROJECT_ROOT / "README.md").read_text()

    assert "pnpm nx run luna-corpus:db-migrate" in readme
    assert "pnpm nx run luna-corpus:serve" in readme
    assert "AUTO_CREATE_TABLES=false" in readme
    assert "APP_ENV=production" in readme
