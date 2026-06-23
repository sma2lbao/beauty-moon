"""Tests for Alembic migration configuration."""

import re
from pathlib import Path


def test_alembic_files_exist():
    project_root = Path(__file__).parents[2]

    assert (project_root / "alembic.ini").is_file()
    assert (project_root / "alembic" / "env.py").is_file()
    assert (
        project_root / "alembic" / "versions" / "20260622_0001_initial_schema.py"
    ).is_file()


def test_alembic_env_exposes_model_metadata():
    from unittest.mock import MagicMock, patch

    from app.db.models import Base

    # alembic.context is a special module that only has 'config' when invoked
    # via the alembic CLI; mock it so exec() works standalone.
    mock_context = MagicMock()
    mock_context.config = MagicMock()
    mock_context.config.config_file_name = None

    namespace = {"__file__": ""}
    project_root = Path(__file__).parents[2]
    env_path = project_root / "alembic" / "env.py"
    namespace["__file__"] = str(env_path)

    with patch("alembic.context", mock_context):
        exec(env_path.read_text(), namespace)

    assert namespace["target_metadata"] is Base.metadata


def test_initial_migration_defines_current_tables():
    project_root = Path(__file__).parents[2]
    migration_path = (
        project_root / "alembic" / "versions" / "20260622_0001_initial_schema.py"
    )
    migration_source = migration_path.read_text()

    for table_name in ["documents", "chunks", "conversations", "messages"]:
        assert re.search(rf'create_table\(\s*"{table_name}"', migration_source), (
            f"create_table call for '{table_name}' not found in migration"
        )


def test_tenant_context_migration_exists():
    project_root = Path(__file__).parents[2]
    migration_path = (
        project_root
        / "alembic"
        / "versions"
        / "20260623_0002_tenant_knowledge_base_context.py"
    )

    assert migration_path.is_file()


def test_tenant_context_migration_defines_required_schema():
    project_root = Path(__file__).parents[2]
    migration_path = (
        project_root
        / "alembic"
        / "versions"
        / "20260623_0002_tenant_knowledge_base_context.py"
    )
    migration_source = migration_path.read_text()

    for table_name in ["tenants", "workspaces", "knowledge_bases"]:
        assert re.search(rf'create_table\(\s*"{table_name}"', migration_source), (
            f"create_table call for '{table_name}' not found in migration"
        )

    assert re.search(r'add_column\(\s*"documents"', migration_source), (
        "add_column call for 'documents' not found in migration"
    )
    assert re.search(r'add_column\(\s*"conversations"', migration_source), (
        "add_column call for 'conversations' not found in migration"
    )
    assert "default-tenant" in migration_source
    assert "default-workspace" in migration_source
    assert "default-knowledge-base" in migration_source


def test_rbac_migration_exists():
    project_root = Path(__file__).parents[2]
    migration_path = (
        project_root
        / "alembic"
        / "versions"
        / "20260623_0003_rbac_enforcement.py"
    )

    assert migration_path.is_file()


def test_rbac_migration_defines_required_schema_and_seed_data():
    project_root = Path(__file__).parents[2]
    migration_path = (
        project_root
        / "alembic"
        / "versions"
        /   "20260623_0003_rbac_enforcement.py"
    )
    migration_source = migration_path.read_text()

    for table_name in [
        "users",
        "permissions",
        "roles",
        "workspace_memberships",
        "role_permissions",
        "workspace_membership_roles",
    ]:
        assert re.search(rf'create_table\(\s*"{table_name}"', migration_source), (
            f"create_table call for '{table_name}' not found in migration"
        )

    for role_slug in ["workspace_admin", "kb_editor", "kb_reader"]:
        assert role_slug in migration_source

    for permission_slug in [
        "workspace:read",
        "workspace:manage",
        "knowledge_base:read",
        "knowledge_base:manage",
        "document:read",
        "document:write",
        "document:delete",
        "conversation:read",
        "conversation:write",
        "conversation:delete",
        "qa:query",
    ]:
        assert permission_slug in migration_source

    assert "bulk_insert" in migration_source
