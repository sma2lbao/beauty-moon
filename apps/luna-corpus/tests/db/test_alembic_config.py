"""Tests for Alembic migration configuration."""

import re
from pathlib import Path


def test_alembic_files_exist():
    project_root = Path(__file__).parents[2]

    assert (project_root / "alembic.ini").is_file()
    assert (project_root / "alembic" / "env.py").is_file()
    assert (
        project_root
        / "alembic"
        / "versions"
        / "20260622_0001_initial_schema.py"
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
        project_root
        / "alembic"
        / "versions"
        / "20260622_0001_initial_schema.py"
    )
    migration_source = migration_path.read_text()

    for table_name in ["documents", "chunks", "conversations", "messages"]:
        assert re.search(
            rf'create_table\(\s*"{table_name}"', migration_source
        ), f"create_table call for '{table_name}' not found in migration"
