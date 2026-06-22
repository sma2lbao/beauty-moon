# P0-M1 Migration Config Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the P0-M1 migration and configuration foundation for `apps/luna-corpus`.

**Architecture:** Introduce Alembic as the schema migration boundary, extend `Settings` as the configuration boundary, and make FastAPI startup/CORS behavior depend on validated settings. Expose migration commands through Nx targets and document the standard development and production workflow.

**Tech Stack:** Python 3.11+, FastAPI, Pydantic Settings v2, SQLAlchemy 2, Alembic, Nx `run-commands`, uv, pytest.

## Global Constraints

- Do not implement Tenant, Workspace, KnowledgeBase, User, Membership, RBAC, JWT/OIDC, file upload, async indexing, Docker, or Compose in this plan.
- Alembic initial migration is for rebuildable environments only; do not implement production baseline/stamp flows.
- Production must reject `APP_ENV=production` with `AUTO_CREATE_TABLES=true`.
- Production must reject empty CORS origins and wildcard `*` CORS origins.
- All project tasks must be runnable through `pnpm nx run luna-corpus:<target>` where a target exists.
- Prefer Nx commands over direct underlying tools when running lint/test/build for the workspace.

---

## File Structure

- Modify `apps/luna-corpus/pyproject.toml`: add Alembic dependency.
- Create `apps/luna-corpus/alembic.ini`: Alembic config scoped to the app directory.
- Create `apps/luna-corpus/alembic/env.py`: loads app settings and SQLAlchemy metadata for migrations.
- Create `apps/luna-corpus/alembic/versions/20260622_0001_initial_schema.py`: initial migration for current models.
- Modify `apps/luna-corpus/app/core/config.py`: add environment enum, CORS parsing, and production safety validation.
- Create `apps/luna-corpus/tests/core/test_config.py`: focused tests for settings behavior.
- Modify `apps/luna-corpus/app/main.py`: use configured CORS and guard `init_db()` behind `auto_create_tables`.
- Create `apps/luna-corpus/tests/test_main.py`: startup and CORS tests.
- Modify `apps/luna-corpus/project.json`: add `db-migrate` and `db-revision` targets.
- Modify `apps/luna-corpus/.env.example`: document P0-M1 env vars.
- Modify `apps/luna-corpus/README.md`: replace placeholder with migration/config runbook.

---

### Task 1: Add Settings Environment and CORS Validation

**Files:**
- Modify: `apps/luna-corpus/app/core/config.py`
- Create: `apps/luna-corpus/tests/core/test_config.py`

**Interfaces:**
- Produces: `AppEnv(str, Enum)` with values `development`, `test`, `production`.
- Produces: `Settings.app_env: AppEnv`.
- Produces: `Settings.auto_create_tables: bool`.
- Produces: `Settings.cors_allow_origins: list[str]`.
- Consumes: existing `Settings` construction behavior from Pydantic Settings.

- [ ] **Step 1: Create the test package directory**

Run: `mkdir -p apps/luna-corpus/tests/core`

Expected: directory exists at `apps/luna-corpus/tests/core`.

- [ ] **Step 2: Write failing configuration tests**

Create `apps/luna-corpus/tests/core/test_config.py` with:

```python
"""Tests for application configuration."""

import pytest
from pydantic import ValidationError

from app.core.config import AppEnv, Settings


def test_default_environment_settings():
    settings = Settings()

    assert settings.app_env == AppEnv.DEVELOPMENT
    assert settings.auto_create_tables is False
    assert settings.cors_allow_origins == []


def test_cors_origins_parse_comma_separated_string():
    settings = Settings(
        cors_allow_origins="http://localhost:3000,http://localhost:4200",
    )

    assert settings.cors_allow_origins == [
        "http://localhost:3000",
        "http://localhost:4200",
    ]


def test_cors_origins_trim_whitespace_and_ignore_empty_values():
    settings = Settings(
        cors_allow_origins=" http://localhost:3000, ,http://localhost:4200 ",
    )

    assert settings.cors_allow_origins == [
        "http://localhost:3000",
        "http://localhost:4200",
    ]


def test_development_allows_auto_create_tables():
    settings = Settings(
        app_env=AppEnv.DEVELOPMENT,
        auto_create_tables=True,
    )

    assert settings.auto_create_tables is True


def test_production_rejects_auto_create_tables():
    with pytest.raises(ValidationError, match="AUTO_CREATE_TABLES must be false"):
        Settings(
            app_env=AppEnv.PRODUCTION,
            auto_create_tables=True,
            cors_allow_origins="https://app.example.com",
        )


def test_production_rejects_empty_cors_origins():
    with pytest.raises(ValidationError, match="CORS_ALLOW_ORIGINS must be set"):
        Settings(app_env=AppEnv.PRODUCTION)


def test_production_rejects_wildcard_cors_origin():
    with pytest.raises(ValidationError, match="wildcard CORS origins"):
        Settings(
            app_env=AppEnv.PRODUCTION,
            cors_allow_origins="*",
        )


def test_production_accepts_explicit_cors_origin():
    settings = Settings(
        app_env=AppEnv.PRODUCTION,
        cors_allow_origins="https://app.example.com",
    )

    assert settings.cors_allow_origins == ["https://app.example.com"]
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pnpm nx run luna-corpus:test -- -- apps/luna-corpus/tests/core/test_config.py -v`

Expected: FAIL because `AppEnv`, `app_env`, `auto_create_tables`, and `cors_allow_origins` do not exist yet.

- [ ] **Step 4: Implement Settings fields and validators**

Modify `apps/luna-corpus/app/core/config.py` to include these imports:

```python
from enum import Enum
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
```

Add this enum after `AgentMode`:

```python
class AppEnv(str, Enum):
    """Application runtime environments."""

    DEVELOPMENT = "development"
    TEST = "test"
    PRODUCTION = "production"
```

Add these fields to `Settings` after the API port fields:

```python
    # Runtime Environment
    app_env: AppEnv = Field(
        default=AppEnv.DEVELOPMENT,
        description="Application runtime environment",
    )
    auto_create_tables: bool = Field(
        default=False,
        description="Automatically create database tables on startup",
    )
    cors_allow_origins: list[str] = Field(
        default_factory=list,
        description="Allowed CORS origins",
    )
```

Add these validators inside `Settings` after the fields:

```python
    @field_validator("cors_allow_origins", mode="before")
    @classmethod
    def parse_cors_allow_origins(cls, value: Any) -> list[str]:
        if value is None or value == "":
            return []
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        if isinstance(value, list):
            return value
        raise TypeError("CORS_ALLOW_ORIGINS must be a comma-separated string or list")

    @model_validator(mode="after")
    def validate_production_safety(self) -> "Settings":
        if self.app_env != AppEnv.PRODUCTION:
            return self

        if self.auto_create_tables:
            raise ValueError("AUTO_CREATE_TABLES must be false in production")

        if not self.cors_allow_origins:
            raise ValueError("CORS_ALLOW_ORIGINS must be set in production")

        if "*" in self.cors_allow_origins:
            raise ValueError("Production cannot use wildcard CORS origins")

        return self
```

- [ ] **Step 5: Run focused configuration tests**

Run: `pnpm nx run luna-corpus:test -- -- apps/luna-corpus/tests/core/test_config.py -v`

Expected: PASS for all tests in `test_config.py`.

- [ ] **Step 6: Run existing integration configuration test**

Run: `pnpm nx run luna-corpus:test -- -- apps/luna-corpus/tests/test_integration.py::test_config_settings -v`

Expected: PASS; existing default settings remain compatible.

- [ ] **Step 7: Commit**

```bash
git add apps/luna-corpus/app/core/config.py apps/luna-corpus/tests/core/test_config.py
git commit -m "feat(corpus): add runtime safety settings"
```

---

### Task 2: Guard Startup Table Creation and Configure CORS

**Files:**
- Modify: `apps/luna-corpus/app/main.py`
- Create: `apps/luna-corpus/tests/test_main.py`

**Interfaces:**
- Consumes: `Settings.auto_create_tables` from Task 1.
- Consumes: `Settings.cors_allow_origins` from Task 1.
- Produces: FastAPI app uses configured CORS origins.
- Produces: lifespan calls `init_db()` only when `settings.auto_create_tables` is true.

- [ ] **Step 1: Write failing startup and CORS tests**

Create `apps/luna-corpus/tests/test_main.py` with:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pnpm nx run luna-corpus:test -- -- apps/luna-corpus/tests/test_main.py -v`

Expected: FAIL because `create_app` does not exist and startup still calls `init_db()` unconditionally.

- [ ] **Step 3: Refactor FastAPI app creation**

Replace `apps/luna-corpus/app/main.py` with:

```python
"""FastAPI application entry point."""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.api.agent_routes import router as agent_router
from app.core.config import get_settings
from app.db.database import init_db

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events."""
    if settings.auto_create_tables:
        init_db()
    yield


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="Luna-Corpus API",
        description="RAG-based Q&A Knowledge Base System",
        version="1.0.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allow_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(router)
    app.include_router(agent_router)

    @app.get("/")
    async def root():
        """Root endpoint."""
        return {"message": "Luna-Corpus API", "version": "1.0.0"}

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=settings.app_env != "production",
    )
```

- [ ] **Step 4: Run startup tests**

Run: `pnpm nx run luna-corpus:test -- -- apps/luna-corpus/tests/test_main.py -v`

Expected: PASS.

- [ ] **Step 5: Run existing app import test**

Run: `pnpm nx run luna-corpus:test -- -- apps/luna-corpus/tests/test_integration.py::test_main_app_import -v`

Expected: PASS; `app` is still importable and has title `Luna-Corpus API`.

- [ ] **Step 6: Commit**

```bash
git add apps/luna-corpus/app/main.py apps/luna-corpus/tests/test_main.py
git commit -m "fix(corpus): guard startup table creation"
```

---

### Task 3: Add Alembic Dependency and Migration Files

**Files:**
- Modify: `apps/luna-corpus/pyproject.toml`
- Create: `apps/luna-corpus/alembic.ini`
- Create: `apps/luna-corpus/alembic/env.py`
- Create: `apps/luna-corpus/alembic/versions/20260622_0001_initial_schema.py`
- Create: `apps/luna-corpus/tests/db/test_alembic_config.py`

**Interfaces:**
- Consumes: `Settings.database_url` from existing config.
- Consumes: `Base.metadata` from `app.db.models`.
- Produces: Alembic target metadata and initial schema migration.

- [ ] **Step 1: Write failing Alembic structure tests**

Create `apps/luna-corpus/tests/db/test_alembic_config.py` with:

```python
"""Tests for Alembic migration configuration."""

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
    from app.db.models import Base

    namespace = {}
    project_root = Path(__file__).parents[2]
    env_path = project_root / "alembic" / "env.py"
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
        assert f'create_table("{table_name}"' in migration_source
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pnpm nx run luna-corpus:test -- -- apps/luna-corpus/tests/db/test_alembic_config.py -v`

Expected: FAIL because Alembic files do not exist yet.

- [ ] **Step 3: Add Alembic dependency**

Modify `apps/luna-corpus/pyproject.toml` dependencies to include:

```toml
    "alembic>=1.13.0",
```

Place it near the SQLAlchemy dependency block.

- [ ] **Step 4: Create Alembic config file**

Create `apps/luna-corpus/alembic.ini` with:

```ini
[alembic]
script_location = alembic
prepend_sys_path = .
version_path_separator = os
sqlalchemy.url = driver://user:pass@localhost/dbname

[post_write_hooks]

[loggers]
keys = root,sqlalchemy,alembic

[handlers]
keys = console

[formatters]
keys = generic

[logger_root]
level = WARN
handlers = console
qualname =

[logger_sqlalchemy]
level = WARN
handlers =
qualname = sqlalchemy.engine

[logger_alembic]
level = INFO
handlers =
qualname = alembic

[handler_console]
class = StreamHandler
args = (sys.stderr,)
level = NOTSET
formatter = generic

[formatter_generic]
format = %(levelname)-5.5s [%(name)s] %(message)s
datefmt = %H:%M:%S
```

- [ ] **Step 5: Create Alembic env.py**

Create directory `apps/luna-corpus/alembic/versions`.

Create `apps/luna-corpus/alembic/env.py` with:

```python
"""Alembic environment configuration."""
from logging.config import fileConfig
from pathlib import Path
import sys

from alembic import context
from sqlalchemy import engine_from_config, pool

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.config import get_settings
from app.db.models import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def get_database_url() -> str:
    return get_settings().database_url


def run_migrations_offline() -> None:
    url = get_database_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = get_database_url()

    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

- [ ] **Step 6: Create initial migration**

Create `apps/luna-corpus/alembic/versions/20260622_0001_initial_schema.py` with:

```python
"""Initial schema.

Revision ID: 20260622_0001
Revises:
Create Date: 2026-06-22
"""
from typing import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision: str = "20260622_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "documents",
        sa.Column("id", mysql.CHAR(36), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("source", sa.String(length=1000), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("has_tables", sa.Boolean(), nullable=False),
        sa.Column("has_code", sa.Boolean(), nullable=False),
        sa.Column(
            "status",
            sa.Enum("PENDING", "PROCESSING", "COMPLETED", "ERROR", name="contentstatus"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "conversations",
        sa.Column("id", mysql.CHAR(36), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "chunks",
        sa.Column("id", mysql.CHAR(36), nullable=False),
        sa.Column("document_id", mysql.CHAR(36), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_type", sa.Enum("TEXT", "TABLE", "CODE", name="contenttype"), nullable=False),
        sa.Column("chunk_metadata", sa.JSON(), nullable=True),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "messages",
        sa.Column("id", mysql.CHAR(36), nullable=False),
        sa.Column("conversation_id", mysql.CHAR(36), nullable=False),
        sa.Column("role", sa.Enum("USER", "ASSISTANT", "SYSTEM", name="messagerole"), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("messages")
    op.drop_table("chunks")
    op.drop_table("conversations")
    op.drop_table("documents")
```

- [ ] **Step 7: Run Alembic structure tests**

Run: `pnpm nx run luna-corpus:test -- -- apps/luna-corpus/tests/db/test_alembic_config.py -v`

Expected: PASS.

- [ ] **Step 8: Run dependency sync if needed**

Run: `pnpm nx run luna-corpus:sync`

Expected: dependency lock/sync completes without errors. If it changes lock files, include those generated changes in the commit.

- [ ] **Step 9: Commit**

```bash
git add apps/luna-corpus/pyproject.toml apps/luna-corpus/alembic.ini apps/luna-corpus/alembic apps/luna-corpus/tests/db/test_alembic_config.py uv.lock
git commit -m "feat(corpus): add alembic initial migration"
```

---

### Task 4: Add Nx Migration Targets

**Files:**
- Modify: `apps/luna-corpus/project.json`
- Create: `apps/luna-corpus/tests/test_project_config.py`

**Interfaces:**
- Consumes: Alembic files from Task 3.
- Produces: Nx targets `db-migrate` and `db-revision`.

- [ ] **Step 1: Write failing project target tests**

Create `apps/luna-corpus/tests/test_project_config.py` with:

```python
"""Tests for Nx project configuration."""

import json
from pathlib import Path


def load_project_config() -> dict:
    project_root = Path(__file__).parents[1]
    return json.loads((project_root / "project.json").read_text())


def test_db_migrate_target_runs_alembic_upgrade_head():
    config = load_project_config()
    target = config["targets"]["db-migrate"]

    assert target["executor"] == "nx:run-commands"
    assert target["options"]["cwd"] == "{projectRoot}"
    assert target["options"]["command"] == "uv run alembic -c alembic.ini upgrade head"


def test_db_revision_target_runs_alembic_autogenerate():
    config = load_project_config()
    target = config["targets"]["db-revision"]

    assert target["executor"] == "nx:run-commands"
    assert target["options"]["cwd"] == "{projectRoot}"
    assert target["options"]["command"] == "uv run alembic -c alembic.ini revision --autogenerate"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pnpm nx run luna-corpus:test -- -- apps/luna-corpus/tests/test_project_config.py -v`

Expected: FAIL because the new targets do not exist.

- [ ] **Step 3: Add project targets**

Modify `apps/luna-corpus/project.json` to add these targets under `targets`:

```json
    "db-migrate": {
      "executor": "nx:run-commands",
      "options": {
        "command": "uv run alembic -c alembic.ini upgrade head",
        "cwd": "{projectRoot}"
      }
    },
    "db-revision": {
      "executor": "nx:run-commands",
      "options": {
        "command": "uv run alembic -c alembic.ini revision --autogenerate",
        "cwd": "{projectRoot}"
      }
    },
```

Keep the JSON valid with commas placed according to neighboring targets.

- [ ] **Step 4: Run project config tests**

Run: `pnpm nx run luna-corpus:test -- -- apps/luna-corpus/tests/test_project_config.py -v`

Expected: PASS.

- [ ] **Step 5: Confirm Nx can resolve the migration target**

Run: `pnpm nx show project luna-corpus --json`

Expected: JSON output includes `db-migrate` and `db-revision` under `targets`.

- [ ] **Step 6: Commit**

```bash
git add apps/luna-corpus/project.json apps/luna-corpus/tests/test_project_config.py
git commit -m "chore(corpus): add database migration targets"
```

---

### Task 5: Document Environment and Migration Workflow

**Files:**
- Modify: `apps/luna-corpus/.env.example`
- Modify: `apps/luna-corpus/README.md`
- Create: `apps/luna-corpus/tests/test_docs.py`

**Interfaces:**
- Consumes: settings from Task 1.
- Consumes: Nx targets from Task 4.
- Produces: documented setup and production constraints.

- [ ] **Step 1: Write failing documentation tests**

Create `apps/luna-corpus/tests/test_docs.py` with:

```python
"""Tests for project documentation and environment examples."""

from pathlib import Path

PROJECT_ROOT = Path(__file__).parents[1]


def test_env_example_documents_runtime_safety_settings():
    env_example = (PROJECT_ROOT / ".env.example").read_text()

    assert "APP_ENV=development" in env_example
    assert "AUTO_CREATE_TABLES=false" in env_example
    assert "CORS_ALLOW_ORIGINS=http://localhost:3000,http://localhost:4200" in env_example


def test_readme_documents_migration_commands():
    readme = (PROJECT_ROOT / "README.md").read_text()

    assert "pnpm nx run luna-corpus:db-migrate" in readme
    assert "pnpm nx run luna-corpus:serve" in readme
    assert "AUTO_CREATE_TABLES=false" in readme
    assert "APP_ENV=production" in readme
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pnpm nx run luna-corpus:test -- -- apps/luna-corpus/tests/test_docs.py -v`

Expected: FAIL because `.env.example` and README do not yet include the new content.

- [ ] **Step 3: Update `.env.example`**

Modify `apps/luna-corpus/.env.example` to include this API/runtime section after `API_PORT=8000`:

```env
# Runtime
APP_ENV=development
AUTO_CREATE_TABLES=false
CORS_ALLOW_ORIGINS=http://localhost:3000,http://localhost:4200
```

- [ ] **Step 4: Replace README placeholder**

Replace `apps/luna-corpus/README.md` with:

```markdown
# luna-corpus

RAG-based Q&A knowledge base API built with FastAPI, SQLAlchemy, Chroma, LangGraph, and configurable LLM providers.

## Prerequisites

- Python managed by `uv`
- Workspace package manager available from the repository root
- MySQL database reachable by `DATABASE_URL`
- Chroma storage path or service configuration
- Ollama, Ark, or Doubao credentials depending on `LLM_PROVIDER`

## Environment

Copy the example file before running locally:

```bash
cp apps/luna-corpus/.env.example apps/luna-corpus/.env
```

Important runtime settings:

- `APP_ENV=development` for local development.
- `APP_ENV=production` for production deployments.
- `AUTO_CREATE_TABLES=false` is the standard path because schema changes are managed by Alembic.
- `CORS_ALLOW_ORIGINS=http://localhost:3000,http://localhost:4200` configures allowed browser origins.

Production must keep `AUTO_CREATE_TABLES=false` and must set explicit CORS origins. Wildcard CORS origins are rejected in production.

## Database migrations

Run migrations from the repository root through Nx:

```bash
pnpm nx run luna-corpus:db-migrate
```

Create a new autogeneration revision after changing SQLAlchemy models:

```bash
pnpm nx run luna-corpus:db-revision
```

Review generated revisions before committing them.

## Local development

Start the API from the repository root:

```bash
pnpm nx run luna-corpus:serve
```

The API listens on `API_HOST` and `API_PORT` from `.env`.

## Tests

Run the app test suite through Nx:

```bash
pnpm nx run luna-corpus:test
```

## Production startup rule

Run `pnpm nx run luna-corpus:db-migrate` before starting the API. The API startup path is not responsible for creating production tables.
```

- [ ] **Step 5: Run documentation tests**

Run: `pnpm nx run luna-corpus:test -- -- apps/luna-corpus/tests/test_docs.py -v`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/luna-corpus/.env.example apps/luna-corpus/README.md apps/luna-corpus/tests/test_docs.py
git commit -m "docs(corpus): document migration configuration"
```

---

### Task 6: Final Verification

**Files:**
- Verify all files changed by Tasks 1-5.

**Interfaces:**
- Consumes: all outputs from Tasks 1-5.
- Produces: verified P0-M1 deliverable.

- [ ] **Step 1: Run the full luna-corpus test target**

Run: `pnpm nx run luna-corpus:test`

Expected: PASS with no failed tests.

- [ ] **Step 2: Run lint target**

Run: `pnpm nx run luna-corpus:lint`

Expected: PASS with no Ruff errors.

- [ ] **Step 3: Verify Nx project targets include migration targets**

Run: `pnpm nx show project luna-corpus --json`

Expected: output includes `db-migrate` and `db-revision` targets.

- [ ] **Step 4: Verify Alembic command can load configuration**

Run: `pnpm nx run luna-corpus:db-revision -- --help`

Expected: command exits successfully and displays Alembic revision help. If Nx forwards arguments differently in this workspace, run `pnpm nx run luna-corpus:db-revision` only in a disposable branch and remove the generated empty revision before committing.

- [ ] **Step 5: Inspect working tree**

Run: `git status --short`

Expected: only intended P0-M1 files are modified before final commit or handoff.

- [ ] **Step 6: Commit verification-only fixes if needed**

If Tasks 1-5 already committed cleanly and no fixes were needed, do not create an empty commit. If verification required fixes, commit only those files:

```bash
git add <fixed-files>
git commit -m "fix(corpus): stabilize migration configuration"
```

---

## Self-Review

- Spec coverage: Alembic initial migration is covered by Task 3; environment and production validation by Task 1; startup and CORS by Task 2; Nx targets by Task 4; README and `.env.example` by Task 5; final test/lint/target verification by Task 6.
- Placeholder scan: the plan does not contain TBD, TODO, FIXME, or unspecified implementation steps.
- Type consistency: `AppEnv`, `Settings.app_env`, `Settings.auto_create_tables`, and `Settings.cors_allow_origins` are introduced in Task 1 and consumed with the same names in later tasks.
