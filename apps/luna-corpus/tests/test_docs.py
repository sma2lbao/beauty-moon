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
    assert "JWT_SECRET_KEY=" in env_example
    assert "ACCESS_TOKEN_EXPIRE_MINUTES=" in env_example


def test_readme_documents_migration_commands():
    readme = (PROJECT_ROOT / "README.md").read_text()

    assert "pnpm nx run luna-corpus:db-migrate" in readme
    assert "pnpm nx run luna-corpus:serve" in readme
    assert "AUTO_CREATE_TABLES=false" in readme
    assert "APP_ENV=production" in readme


def test_readme_documents_knowledge_base_context_headers():
    readme = (PROJECT_ROOT / "README.md").read_text()

    assert "X-Tenant-Id" in readme
    assert "X-Workspace-Id" in readme
    assert "X-Knowledge-Base-Id" in readme
    assert "POST /api/v1/tenants" in readme
    assert "POST /api/v1/knowledge-bases" in readme


def test_readme_documents_auth_and_rbac_context():
    readme = Path(__file__).parents[1] / "README.md"
    content = readme.read_text()

    # Auth is now bearer-token based; the legacy X-User-Id trust is gone.
    assert "Authorization: Bearer" in content
    assert "trust anymore" in content
    assert "workspace_admin" in content
    assert "kb_editor" in content
    assert "kb_reader" in content
    assert "POST /api/v1/tenants" in content
    assert "POST /api/v1/users" in content
    assert "/api/v1/auth/login" in content
    assert "seed_admin.py" in content
