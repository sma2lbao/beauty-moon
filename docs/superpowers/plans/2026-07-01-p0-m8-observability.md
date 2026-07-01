# P0-M8 可观测性代码层 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add structured logging (structlog), Prometheus metrics (`/metrics` + HTTP and business-stage timings), and a component-differentiated health check to `apps/luna-corpus`.

**Architecture:** A new `app/observability/` module mirrors the existing `app/security/` layout. Cross-cutting HTTP metrics and access logs are collected in a middleware; business-stage timings use a `time_stage()` context manager placed inside services; logs auto-bind `request_id`/`user_id`/`tenant_id` via a structlog contextvars processor reading `app/security/context.py`. The health check is upgraded to report per-component status. Observability never breaks the main request — all instrumentation swallows its own errors.

**Tech Stack:** FastAPI/Starlette, structlog, prometheus-client, pytest, SQLAlchemy. Package/test runner: `uv` via Nx.

## Global Constraints

- Python `>=3.11,<4`. Use `str | None` union syntax, `StrEnum`, `contextvars`.
- New dependencies added to `apps/luna-corpus/pyproject.toml`: `structlog>=24.1`, `prometheus-client>=0.20`.
- Follow existing module conventions: docstrings on public functions, `from __future__` not needed (3.11+), `app.*` absolute imports.
- Tests live under `apps/luna-corpus/tests/<area>/`, run via `pnpm nx run luna-corpus:test` or `uv run --project ../.. pytest` from the project dir. Test files use the fixtures in `tests/api/test_file_upload.py` (`app_db`, `client`, `create_user_with_permissions`, `_auth_headers`) re-exported by `tests/api/conftest.py`.
- Observability code MUST NOT raise into the request path: timing `finally`-observes, health checks catch per-component, logging failures are non-fatal.
- Rate-limit exemption list lives in `app/security/middleware.py::_RATE_LIMIT_EXEMPT`; `/metrics` must be added there.
- Run lint before each commit: `pnpm nx run luna-corpus:lint`.

**Working directory for all commands:** `apps/luna-corpus/` unless stated otherwise.

---

### Task 1: Add dependencies and observability config

**Files:**
- Modify: `apps/luna-corpus/pyproject.toml` (dependencies list)
- Modify: `apps/luna-corpus/app/core/config.py` (add `LogFormat` enum + 3 settings)
- Test: `apps/luna-corpus/tests/core/test_config.py` (add cases)

**Interfaces:**
- Produces: `Settings.log_level: str` (default `"INFO"`), `Settings.log_format: LogFormat`, `Settings.metrics_enabled: bool` (default `True`); `LogFormat` StrEnum with `JSON = "json"`, `CONSOLE = "console"`; a `model_validator` that defaults `log_format` from `app_env` when unset.

- [ ] **Step 1: Add the failing config test**

Add to `apps/luna-corpus/tests/core/test_config.py` (create if missing, matching existing config-test style):

```python
from app.core.config import AppEnv, LogFormat, Settings


def test_log_format_defaults_to_json_in_production():
    s = Settings(app_env=AppEnv.PRODUCTION, database_url="sqlite://")
    assert s.log_format == LogFormat.JSON


def test_log_format_defaults_to_console_in_development():
    s = Settings(app_env=AppEnv.DEVELOPMENT, database_url="sqlite://")
    assert s.log_format == LogFormat.CONSOLE


def test_metrics_enabled_defaults_true():
    s = Settings(database_url="sqlite://")
    assert s.metrics_enabled is True
    assert s.log_level == "INFO"


def test_explicit_log_format_overrides_env_default():
    s = Settings(app_env=AppEnv.PRODUCTION, log_format=LogFormat.CONSOLE,
                 database_url="sqlite://")
    assert s.log_format == LogFormat.CONSOLE
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --project ../.. pytest tests/core/test_config.py -k log_format -v`
Expected: FAIL with `ImportError: cannot import name 'LogFormat'`.

- [ ] **Step 3: Add the `LogFormat` enum and settings**

In `apps/luna-corpus/app/core/config.py`, add the enum next to the other StrEnums (after `AppEnv`):

```python
class LogFormat(StrEnum):
    """Structured log output formats."""

    JSON = "json"
    CONSOLE = "console"
```

Inside `class Settings`, add these fields (place them after the `app_env` field around line 137):

```python
    # Observability
    log_level: str = Field(default="INFO")
    log_format: LogFormat | None = Field(
        default=None,
        description="Log output format; defaults from app_env when unset.",
    )
    metrics_enabled: bool = Field(default=True)
```

Add a `model_validator` method inside `Settings` (mode="after"):

```python
    @model_validator(mode="after")
    def _default_log_format(self) -> "Settings":
        if self.log_format is None:
            self.log_format = (
                LogFormat.JSON
                if self.app_env == AppEnv.PRODUCTION
                else LogFormat.CONSOLE
            )
        return self
```

Note: `model_validator` is already imported (config.py line 7). The `Settings` model is not frozen, so plain attribute assignment works. There is already one `@model_validator(mode="after")` (`validate_production_safety` at line 229) — add this as a second one; pydantic runs all after-validators.

- [ ] **Step 4: Add dependencies to pyproject.toml**

In `apps/luna-corpus/pyproject.toml`, add to the `dependencies` list (after the ingestion parsers block):

```toml
    # Observability
    "structlog>=24.1",
    "prometheus-client>=0.20",
```

Then sync from the repo root:

Run (from repo root): `pnpm nx run luna-corpus:lock && pnpm nx run luna-corpus:sync`
Expected: lockfile updates, `structlog` and `prometheus-client` installed.

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run --project ../.. pytest tests/core/test_config.py -k "log_format or metrics_enabled" -v`
Expected: PASS (4 tests).

- [ ] **Step 6: Commit**

```bash
git add apps/luna-corpus/pyproject.toml apps/luna-corpus/uv.lock apps/luna-corpus/app/core/config.py apps/luna-corpus/tests/core/test_config.py
git commit -m "feat(corpus): add observability deps and config"
```

---

### Task 2: Extend request context with user_id / tenant_id

**Files:**
- Modify: `apps/luna-corpus/app/security/context.py`
- Test: `apps/luna-corpus/tests/security/test_context.py`

**Interfaces:**
- Consumes: existing `set_request_context(request_id, client_ip)`, `reset_request_context()`, contextvars `_request_id`, `_client_ip`.
- Produces: `set_identity_context(user_id: str | None, tenant_id: str | None) -> None`, `get_user_id() -> str | None`, `get_tenant_id() -> str | None`. `reset_request_context()` also clears identity vars.

- [ ] **Step 1: Write the failing test**

Add to `apps/luna-corpus/tests/security/test_context.py`:

```python
from app.security.context import (
    get_tenant_id,
    get_user_id,
    reset_request_context,
    set_identity_context,
)


def test_identity_context_roundtrip():
    set_identity_context("user-1", "tenant-1")
    assert get_user_id() == "user-1"
    assert get_tenant_id() == "tenant-1"
    reset_request_context()
    assert get_user_id() is None
    assert get_tenant_id() is None


def test_identity_defaults_none():
    reset_request_context()
    assert get_user_id() is None
    assert get_tenant_id() is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --project ../.. pytest tests/security/test_context.py -k identity -v`
Expected: FAIL with `ImportError: cannot import name 'set_identity_context'`.

- [ ] **Step 3: Add identity contextvars**

In `apps/luna-corpus/app/security/context.py`, after the existing `_client_ip` ContextVar, add:

```python
_user_id: ContextVar[str | None] = ContextVar("user_id", default=None)
_tenant_id: ContextVar[str | None] = ContextVar("tenant_id", default=None)


def set_identity_context(user_id: str | None, tenant_id: str | None) -> None:
    """Store the authenticated user_id and tenant_id for the request scope."""
    _user_id.set(user_id)
    _tenant_id.set(tenant_id)


def get_user_id() -> str | None:
    """Return the current user_id, or None if unset."""
    return _user_id.get()


def get_tenant_id() -> str | None:
    """Return the current tenant_id, or None if unset."""
    return _tenant_id.get()
```

Then extend `reset_request_context()` to also clear them:

```python
def reset_request_context() -> None:
    """Clear the request context (request_id, client IP, identity)."""
    _request_id.set(None)
    _client_ip.set(None)
    _user_id.set(None)
    _tenant_id.set(None)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --project ../.. pytest tests/security/test_context.py -k identity -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add apps/luna-corpus/app/security/context.py apps/luna-corpus/tests/security/test_context.py
git commit -m "feat(corpus): add user_id/tenant_id to request context"
```

---

### Task 3: Backfill identity context from the auth dependency

**Files:**
- Modify: `apps/luna-corpus/app/api/auth.py` (`get_authenticated_context`, before returning)
- Test: `apps/luna-corpus/tests/security/test_identity_backfill.py` (create)

**Interfaces:**
- Consumes: `set_identity_context` (Task 2), `get_authenticated_context(...)` (existing, `app/api/auth.py:21`).
- Produces: after `get_authenticated_context` succeeds, the request-scoped `user_id` = `user.id` and `tenant_id` = `resource_context.tenant.id` are set.

- [ ] **Step 1: Write the failing test**

Create `apps/luna-corpus/tests/security/test_identity_backfill.py`:

```python
"""get_authenticated_context backfills identity contextvars."""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.auth import get_authenticated_context
from app.db.database import Base
from app.db.models import (
    KnowledgeBase,
    Permission,
    Role,
    Tenant,
    User,
    Workspace,
    WorkspaceMembership,
)
from app.security.context import get_tenant_id, get_user_id, reset_request_context


def test_authenticated_context_sets_identity():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine)()
    reset_request_context()

    tenant = Tenant(name="Acme", slug="acme")
    workspace = Workspace(name="R", slug="r", tenant=tenant)
    kb = KnowledgeBase(name="Docs", slug="docs", workspace=workspace)
    perm = Permission(name="qa:query", slug="qa:query", description="q")
    role = Role(name="reader", slug="reader", is_system=True, permissions=[perm])
    user = User(email="u@example.com", display_name="U")
    membership = WorkspaceMembership(user=user, workspace=workspace, roles=[role])
    db.add_all([kb, membership])
    db.commit()

    get_authenticated_context(
        db=db,
        x_user_id=user.id,
        x_tenant_id=tenant.id,
        x_workspace_id=workspace.id,
        x_knowledge_base_id=kb.id,
        required_permissions=["qa:query"],
    )

    assert get_user_id() == user.id
    assert get_tenant_id() == tenant.id
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --project ../.. pytest tests/security/test_identity_backfill.py -v`
Expected: FAIL — `get_user_id()` returns `None`.

- [ ] **Step 3: Backfill identity before returning**

In `apps/luna-corpus/app/api/auth.py`, add the import at top:

```python
from app.security.context import set_identity_context
```

In `get_authenticated_context`, immediately before the final `return AuthenticatedRequestContext(...)`, add:

```python
    set_identity_context(user.id, resource_context.tenant.id)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --project ../.. pytest tests/security/test_identity_backfill.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/luna-corpus/app/api/auth.py apps/luna-corpus/tests/security/test_identity_backfill.py
git commit -m "feat(corpus): backfill identity context in auth dependency"
```

---

### Task 4: Structured logging configuration

**Files:**
- Create: `apps/luna-corpus/app/observability/__init__.py` (empty)
- Create: `apps/luna-corpus/app/observability/logging.py`
- Test: `apps/luna-corpus/tests/observability/__init__.py` (empty), `apps/luna-corpus/tests/observability/test_logging.py`

**Interfaces:**
- Consumes: `get_request_id`, `get_user_id`, `get_tenant_id`, `get_client_ip` from `app.security.context`; `Settings.log_level`, `Settings.log_format`.
- Produces: `configure_logging(settings) -> None` (idempotent), `get_logger(name: str = "luna") -> structlog.BoundLogger`, and a processor `bind_request_context(logger, method_name, event_dict) -> dict` that injects `request_id`/`user_id`/`tenant_id`/`client_ip` when present.

- [ ] **Step 1: Write the failing test**

Create `apps/luna-corpus/tests/observability/__init__.py` (empty) and `apps/luna-corpus/tests/observability/test_logging.py`:

```python
"""Structured logging configuration tests."""
import json
import logging

from app.core.config import AppEnv, LogFormat, Settings
from app.observability.logging import (
    bind_request_context,
    configure_logging,
    get_logger,
)
from app.security.context import reset_request_context, set_identity_context


def test_bind_request_context_injects_identity():
    reset_request_context()
    set_identity_context("user-9", "tenant-9")
    event = bind_request_context(None, "info", {"event": "hi"})
    assert event["user_id"] == "user-9"
    assert event["tenant_id"] == "tenant-9"
    reset_request_context()


def test_bind_request_context_omits_unset_fields():
    reset_request_context()
    event = bind_request_context(None, "info", {"event": "hi"})
    assert "user_id" not in event
    assert "tenant_id" not in event


def test_json_logging_emits_json(capsys):
    settings = Settings(app_env=AppEnv.PRODUCTION, log_format=LogFormat.JSON,
                        database_url="sqlite://")
    configure_logging(settings)
    reset_request_context()
    set_identity_context("user-1", "tenant-1")
    get_logger("test").info("request_done", status=200)
    reset_request_context()

    out = capsys.readouterr().out.strip().splitlines()[-1]
    payload = json.loads(out)
    assert payload["event"] == "request_done"
    assert payload["status"] == 200
    assert payload["user_id"] == "user-1"


def test_stdlib_logging_bridged(capsys):
    settings = Settings(app_env=AppEnv.PRODUCTION, log_format=LogFormat.JSON,
                        database_url="sqlite://")
    configure_logging(settings)
    logging.getLogger("uvicorn.error").warning("bridged message")
    out = capsys.readouterr().out
    assert "bridged message" in out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --project ../.. pytest tests/observability/test_logging.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.observability'`.

- [ ] **Step 3: Create the logging module**

Create empty `apps/luna-corpus/app/observability/__init__.py`.

Create `apps/luna-corpus/app/observability/logging.py`:

```python
"""structlog configuration with request-context binding."""
import logging
import sys

import structlog

from app.core.config import LogFormat, Settings
from app.security.context import (
    get_client_ip,
    get_request_id,
    get_tenant_id,
    get_user_id,
)


def bind_request_context(logger, method_name, event_dict):
    """structlog processor: inject request-scoped identity when present."""
    request_id = get_request_id()
    if request_id is not None:
        event_dict["request_id"] = request_id
    user_id = get_user_id()
    if user_id is not None:
        event_dict["user_id"] = user_id
    tenant_id = get_tenant_id()
    if tenant_id is not None:
        event_dict["tenant_id"] = tenant_id
    client_ip = get_client_ip()
    if client_ip is not None:
        event_dict["client_ip"] = client_ip
    return event_dict


def configure_logging(settings: Settings) -> None:
    """Configure structlog + stdlib bridge. Idempotent."""
    level = getattr(logging, settings.log_level.upper(), logging.INFO)

    shared_processors = [
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        bind_request_context,
    ]
    if settings.log_format == LogFormat.JSON:
        renderer = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer()

    structlog.configure(
        processors=[*shared_processors, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )

    # Bridge stdlib logging (uvicorn, sqlalchemy) through the same stdout sink.
    root = logging.getLogger()
    root.handlers.clear()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=shared_processors,
            processor=renderer,
        )
    )
    root.addHandler(handler)
    root.setLevel(level)


def get_logger(name: str = "luna"):
    """Return a bound structlog logger."""
    return structlog.get_logger(name)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --project ../.. pytest tests/observability/test_logging.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add apps/luna-corpus/app/observability/__init__.py apps/luna-corpus/app/observability/logging.py apps/luna-corpus/tests/observability/
git commit -m "feat(corpus): add structlog structured logging"
```

---

### Task 5: Metrics definitions and time_stage helper

**Files:**
- Create: `apps/luna-corpus/app/observability/metrics.py`
- Test: `apps/luna-corpus/tests/observability/test_metrics.py`

**Interfaces:**
- Produces:
  - Counter `HTTP_REQUESTS_TOTAL` (labels `method`, `path_template`, `status`)
  - Histogram `HTTP_REQUEST_DURATION` (labels `method`, `path_template`)
  - Histogram `RAG_RETRIEVAL_DURATION` (no labels)
  - Histogram `LLM_GENERATION_DURATION` (label `provider`)
  - Histogram `EMBEDDING_DURATION` (label `provider`)
  - Histogram `INDEX_TASK_DURATION` (label `result`)
  - `time_stage(histogram, **labels)` — context manager, observes elapsed seconds in `finally`
  - `render_metrics() -> tuple[bytes, str]` returning `(generate_latest(), CONTENT_TYPE_LATEST)`

- [ ] **Step 1: Write the failing test**

Create `apps/luna-corpus/tests/observability/test_metrics.py`:

```python
"""Metric definitions and time_stage helper tests."""
import pytest

from app.observability.metrics import (
    EMBEDDING_DURATION,
    RAG_RETRIEVAL_DURATION,
    render_metrics,
    time_stage,
)


def _sample_count(histogram, **labels):
    metric = histogram.labels(**labels) if labels else histogram
    return metric._sum.get(), sum(b.get() for b in metric._buckets)


def test_time_stage_observes_on_success():
    before = RAG_RETRIEVAL_DURATION._sum.get()
    with time_stage(RAG_RETRIEVAL_DURATION):
        pass
    assert RAG_RETRIEVAL_DURATION._sum.get() >= before


def test_time_stage_observes_on_exception():
    before = EMBEDDING_DURATION.labels(provider="ark")._sum.get()
    with pytest.raises(ValueError):
        with time_stage(EMBEDDING_DURATION, provider="ark"):
            raise ValueError("boom")
    after = EMBEDDING_DURATION.labels(provider="ark")._sum.get()
    assert after >= before


def test_render_metrics_returns_prometheus_text():
    body, content_type = render_metrics()
    assert b"rag_retrieval_duration_seconds" in body
    assert "text/plain" in content_type
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --project ../.. pytest tests/observability/test_metrics.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.observability.metrics'`.

- [ ] **Step 3: Create the metrics module**

Create `apps/luna-corpus/app/observability/metrics.py`:

```python
"""Prometheus metric definitions and a timing context manager."""
import time
from contextlib import contextmanager

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Histogram,
    generate_latest,
)

HTTP_REQUESTS_TOTAL = Counter(
    "http_requests_total",
    "Total HTTP requests.",
    ["method", "path_template", "status"],
)
HTTP_REQUEST_DURATION = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency in seconds.",
    ["method", "path_template"],
)
RAG_RETRIEVAL_DURATION = Histogram(
    "rag_retrieval_duration_seconds",
    "Vector retrieval latency in seconds.",
)
LLM_GENERATION_DURATION = Histogram(
    "llm_generation_duration_seconds",
    "LLM generation latency in seconds.",
    ["provider"],
)
EMBEDDING_DURATION = Histogram(
    "embedding_duration_seconds",
    "Embedding latency in seconds.",
    ["provider"],
)
INDEX_TASK_DURATION = Histogram(
    "index_task_duration_seconds",
    "Index task duration in seconds.",
    ["result"],
)


@contextmanager
def time_stage(histogram, **labels):
    """Observe elapsed seconds into `histogram`, even on exception."""
    start = time.perf_counter()
    try:
        yield
    finally:
        elapsed = time.perf_counter() - start
        target = histogram.labels(**labels) if labels else histogram
        target.observe(elapsed)


def render_metrics() -> tuple[bytes, str]:
    """Return the Prometheus exposition payload and content type."""
    return generate_latest(), CONTENT_TYPE_LATEST
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --project ../.. pytest tests/observability/test_metrics.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add apps/luna-corpus/app/observability/metrics.py apps/luna-corpus/tests/observability/test_metrics.py
git commit -m "feat(corpus): add prometheus metrics and time_stage helper"
```

---

### Task 6: Metrics middleware + access log

**Files:**
- Create: `apps/luna-corpus/app/observability/middleware.py`
- Test: `apps/luna-corpus/tests/observability/test_metrics_middleware.py`

**Interfaces:**
- Consumes: `HTTP_REQUESTS_TOTAL`, `HTTP_REQUEST_DURATION` (Task 5); `get_logger` (Task 4); `Settings.metrics_enabled`.
- Produces: `MetricsMiddleware(BaseHTTPMiddleware)`; module fn `resolve_path_template(request) -> str` returning `request.scope["route"].path` or `"unmatched"`.

- [ ] **Step 1: Write the failing test**

Create `apps/luna-corpus/tests/observability/test_metrics_middleware.py`:

```python
"""MetricsMiddleware records counts, durations, and access logs."""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.observability.metrics import HTTP_REQUESTS_TOTAL
from app.observability.middleware import MetricsMiddleware


def _build_app():
    app = FastAPI()
    app.add_middleware(MetricsMiddleware)

    @app.get("/items/{item_id}")
    async def item(item_id: str):
        return {"id": item_id}

    return app


def test_request_counted_with_path_template():
    client = TestClient(_build_app())
    before = HTTP_REQUESTS_TOTAL.labels(
        method="GET", path_template="/items/{item_id}", status="200"
    )._value.get()
    client.get("/items/abc")
    client.get("/items/xyz")
    after = HTTP_REQUESTS_TOTAL.labels(
        method="GET", path_template="/items/{item_id}", status="200"
    )._value.get()
    # Both distinct paths collapse into one templated series.
    assert after - before == 2


def test_unmatched_route_labeled_unmatched():
    client = TestClient(_build_app())
    before = HTTP_REQUESTS_TOTAL.labels(
        method="GET", path_template="unmatched", status="404"
    )._value.get()
    client.get("/nope")
    after = HTTP_REQUESTS_TOTAL.labels(
        method="GET", path_template="unmatched", status="404"
    )._value.get()
    assert after - before == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --project ../.. pytest tests/observability/test_metrics_middleware.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.observability.middleware'`.

- [ ] **Step 3: Create the middleware**

Create `apps/luna-corpus/app/observability/middleware.py`:

```python
"""HTTP metrics + access-log middleware."""
import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.config import get_settings
from app.observability.logging import get_logger
from app.observability.metrics import HTTP_REQUEST_DURATION, HTTP_REQUESTS_TOTAL

_logger = get_logger("luna.access")


def resolve_path_template(request: Request) -> str:
    """Return the matched route template, or 'unmatched'."""
    route = request.scope.get("route")
    if route is not None and getattr(route, "path", None):
        return route.path
    return "unmatched"


class MetricsMiddleware(BaseHTTPMiddleware):
    """Record request count/duration and emit a structured access log."""

    async def dispatch(self, request: Request, call_next) -> Response:
        if not get_settings().metrics_enabled:
            return await call_next(request)

        start = time.perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        finally:
            elapsed = time.perf_counter() - start
            template = resolve_path_template(request)
            method = request.method
            try:
                HTTP_REQUESTS_TOTAL.labels(
                    method=method,
                    path_template=template,
                    status=str(status_code),
                ).inc()
                HTTP_REQUEST_DURATION.labels(
                    method=method, path_template=template
                ).observe(elapsed)
                _logger.info(
                    "request_completed",
                    method=method,
                    path=template,
                    status=status_code,
                    latency_ms=round(elapsed * 1000, 2),
                )
            except Exception:  # observability must never break the request
                pass
```

Note: `request.scope["route"]` is only populated after routing; when `call_next` runs the route it is set. For 404s no route matches → `resolve_path_template` returns `"unmatched"`.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --project ../.. pytest tests/observability/test_metrics_middleware.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add apps/luna-corpus/app/observability/middleware.py apps/luna-corpus/tests/observability/test_metrics_middleware.py
git commit -m "feat(corpus): add metrics middleware with access log"
```

---

### Task 7: Wire logging + middleware + /metrics endpoint into the app

**Files:**
- Modify: `apps/luna-corpus/app/main.py`
- Modify: `apps/luna-corpus/app/security/middleware.py` (`_RATE_LIMIT_EXEMPT`)
- Test: `apps/luna-corpus/tests/observability/test_metrics_endpoint.py`

**Interfaces:**
- Consumes: `configure_logging` (Task 4), `MetricsMiddleware` (Task 6), `render_metrics` (Task 5).
- Produces: `GET /metrics` returning Prometheus text (200) when enabled, `404` when `metrics_enabled=False`; `MetricsMiddleware` registered; `configure_logging(settings)` called in `create_app`; `/metrics` added to `_RATE_LIMIT_EXEMPT`.

- [ ] **Step 1: Write the failing test**

Create `apps/luna-corpus/tests/observability/test_metrics_endpoint.py`:

```python
"""/metrics endpoint behavior."""
from fastapi.testclient import TestClient

from app.main import create_app
from app.security.middleware import _RATE_LIMIT_EXEMPT


def test_metrics_endpoint_exposes_prometheus():
    client = TestClient(create_app())
    resp = client.get("/metrics")
    assert resp.status_code == 200
    assert "text/plain" in resp.headers["content-type"]
    assert "http_requests_total" in resp.text


def test_metrics_endpoint_exempt_from_rate_limit():
    assert "/metrics" in _RATE_LIMIT_EXEMPT


def test_metrics_disabled_returns_404(monkeypatch):
    from app.core import config

    monkeypatch.setattr(
        config.get_settings(), "metrics_enabled", False, raising=False
    )
    client = TestClient(create_app())
    resp = client.get("/metrics")
    assert resp.status_code == 404
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --project ../.. pytest tests/observability/test_metrics_endpoint.py -v`
Expected: FAIL — `/metrics` returns 404 (route not defined yet).

- [ ] **Step 3: Add /metrics to rate-limit exemptions**

In `apps/luna-corpus/app/security/middleware.py`, update line 14:

```python
_RATE_LIMIT_EXEMPT = {"/", "/health", "/metrics", f"{_API_PREFIX}/health"}
```

- [ ] **Step 4: Wire into main.py**

In `apps/luna-corpus/app/main.py`, add imports:

```python
from fastapi import FastAPI, HTTPException, Response
from app.observability.logging import configure_logging
from app.observability.metrics import render_metrics
from app.observability.middleware import MetricsMiddleware
```

In `create_app()`, call `configure_logging(settings)` as the first line. Register the metrics middleware (add it so it runs outermost for accurate timing — added last means outermost in Starlette). After the existing `app.add_middleware(RequestContextMiddleware)` line, add:

```python
    app.add_middleware(MetricsMiddleware)
```

Add the endpoint next to the existing `root` route:

```python
    @app.get("/metrics")
    async def metrics():
        if not settings.metrics_enabled:
            raise HTTPException(status_code=404, detail="Not found")
        body, content_type = render_metrics()
        return Response(content=body, media_type=content_type)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run --project ../.. pytest tests/observability/test_metrics_endpoint.py -v`
Expected: PASS (3 tests).

- [ ] **Step 6: Run the full app-init test to catch regressions**

Run: `uv run --project ../.. pytest tests/test_main.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add apps/luna-corpus/app/main.py apps/luna-corpus/app/security/middleware.py apps/luna-corpus/tests/observability/test_metrics_endpoint.py
git commit -m "feat(corpus): wire logging, metrics middleware, /metrics endpoint"
```

---

### Task 8: Instrument business stages (retrieval, LLM, embedding, index)

**Files:**
- Modify: `apps/luna-corpus/app/graph/rag_graph.py` (`retrieve_node`, `generate_node`)
- Modify: `apps/luna-corpus/app/services/llm.py` (`embed_text`, `embed_texts`)
- Modify: `apps/luna-corpus/app/api/routes.py` (`_run_index_task`)
- Test: `apps/luna-corpus/tests/observability/test_stage_timings.py`

**Interfaces:**
- Consumes: `time_stage`, `RAG_RETRIEVAL_DURATION`, `LLM_GENERATION_DURATION`, `EMBEDDING_DURATION`, `INDEX_TASK_DURATION` (Task 5); `get_settings().llm_provider.value` for the `provider` label.

- [ ] **Step 1: Write the failing test**

Create `apps/luna-corpus/tests/observability/test_stage_timings.py`:

```python
"""Business-stage timing instrumentation."""
from unittest.mock import patch

from app.observability.metrics import EMBEDDING_DURATION, RAG_RETRIEVAL_DURATION


def test_embed_text_records_duration():
    provider = "ark"
    before = EMBEDDING_DURATION.labels(provider=provider)._sum.get()
    with patch("app.services.llm.get_embeddings_model") as m, patch(
        "app.services.llm.get_settings"
    ) as s:
        s.return_value.llm_provider.value = provider
        m.return_value.embed_query.return_value = [0.1, 0.2]
        from app.services.llm import embed_text

        embed_text("hello")
    after = EMBEDDING_DURATION.labels(provider=provider)._sum.get()
    assert after >= before


def test_retrieve_node_records_duration():
    before = RAG_RETRIEVAL_DURATION._sum.get()
    with patch("app.graph.rag_graph.embed_text", return_value=[0.1]), patch(
        "app.graph.rag_graph.search_vectorstore", return_value=[]
    ):
        from app.graph.rag_graph import retrieve_node

        retrieve_node({"question": "q", "knowledge_base_id": "kb-1"})
    after = RAG_RETRIEVAL_DURATION._sum.get()
    assert after >= before
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --project ../.. pytest tests/observability/test_stage_timings.py -v`
Expected: FAIL — durations unchanged (no instrumentation yet). Note: if `get_settings` isn't yet imported in `llm.py`, the embed test fails on patch target; Step 3 adds usage.

- [ ] **Step 3a: Instrument retrieval in rag_graph.py**

In `apps/luna-corpus/app/graph/rag_graph.py`, add import near the top (with the other `app.` imports):

```python
from app.observability.metrics import (
    LLM_GENERATION_DURATION,
    RAG_RETRIEVAL_DURATION,
    time_stage,
)
```

In `retrieve_node` (line ~124), wrap the vector search. Replace:

```python
    # Search vector store
    results = search_vectorstore(
        query_embedding=query_embedding,
        top_k=settings.retrieval_top_k,
        knowledge_base_id=knowledge_base_id,
    )
```

with:

```python
    # Search vector store
    with time_stage(RAG_RETRIEVAL_DURATION):
        results = search_vectorstore(
            query_embedding=query_embedding,
            top_k=settings.retrieval_top_k,
            knowledge_base_id=knowledge_base_id,
        )
```

- [ ] **Step 3b: Instrument LLM generation in rag_graph.py**

In `generate_node` (line ~201), replace:

```python
    # Generate response
    answer = generate_response(prompt=full_prompt, context=None)
```

with:

```python
    # Generate response
    with time_stage(LLM_GENERATION_DURATION, provider=settings.llm_provider.value):
        answer = generate_response(prompt=full_prompt, context=None)
```

Note: `settings` is module-level in `rag_graph.py` (used at line 124 as `settings.retrieval_top_k`), so `settings.llm_provider.value` is available.

- [ ] **Step 3c: Instrument embeddings in llm.py**

In `apps/luna-corpus/app/services/llm.py`, add the metrics import (`get_settings` is already imported at line 9, and `time` at line 4):

```python
from app.observability.metrics import EMBEDDING_DURATION, time_stage
```

Replace `embed_text`'s body:

```python
def embed_text(text: str) -> list[float]:
    """Generate embedding for a single text."""
    embeddings = get_embeddings_model()
    provider = get_settings().llm_provider.value
    with time_stage(EMBEDDING_DURATION, provider=provider):
        return embeddings.embed_query(text)
```

Replace `embed_texts`'s body:

```python
def embed_texts(texts: list[str]) -> list[list[float]]:
    """Generate embeddings for multiple texts."""
    embeddings = get_embeddings_model()
    provider = get_settings().llm_provider.value
    with time_stage(EMBEDDING_DURATION, provider=provider):
        return embeddings.embed_documents(texts)
```

- [ ] **Step 3d: Instrument the index task in routes.py**

In `apps/luna-corpus/app/api/routes.py`, add to the observability imports (top of file):

```python
from app.observability.metrics import INDEX_TASK_DURATION, time_stage
```

In `_run_index_task` (line 257), wrap the processing. Replace:

```python
        processor = DocumentProcessor()
        processor.process_document(db, document_id)

        task_service.mark_completed(db, task_id)
```

with:

```python
        processor = DocumentProcessor()
        with time_stage(INDEX_TASK_DURATION, result="success"):
            processor.process_document(db, document_id)

        task_service.mark_completed(db, task_id)
```

And in the `except Exception as e:` branch, record the failure timing label by wrapping is not possible post-hoc; instead observe a failure sample. Immediately after `task_service.mark_failed(...)` add:

```python
        INDEX_TASK_DURATION.labels(result="failure").observe(0.0)
```

Note: the failure duration is recorded as a marker (0.0) because the elapsed time is already lost in the except branch; the `result="failure"` counter/series is what matters for alerting. Keep it simple — do not restructure the try/except.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --project ../.. pytest tests/observability/test_stage_timings.py -v`
Expected: PASS (2 tests).

Run regression on affected areas:
Run: `uv run --project ../.. pytest tests/graph/test_rag_graph.py tests/services -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/luna-corpus/app/graph/rag_graph.py apps/luna-corpus/app/services/llm.py apps/luna-corpus/app/api/routes.py apps/luna-corpus/tests/observability/test_stage_timings.py
git commit -m "feat(corpus): instrument retrieval, LLM, embedding, index timings"
```

---

### Task 9: Component-differentiated health check

**Files:**
- Modify: `apps/luna-corpus/app/api/routes.py` (`HealthResponse` model ~line 122, `health_check` ~line 1381)
- Test: `apps/luna-corpus/tests/api/test_health_check.py` (create)

**Interfaces:**
- Consumes: `get_db`, `get_vector_store`, `check_ollama_health`/`check_ark_health`/`check_doubao_health`, `get_settings().llm_provider`.
- Produces: `HealthResponse` with `status: str` and `components: dict[str, dict]`; each component has `status` in `{up, down, not_configured}` and optional `latency_ms` / `provider`. Overall `status` is `degraded` if database or vectorstore is `down`, else `ok`.

- [ ] **Step 1: Write the failing test**

Create `apps/luna-corpus/tests/api/test_health_check.py`:

```python
"""Component-differentiated health check."""
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import create_app


def test_health_all_up():
    with patch("app.db.vectorstore.get_vector_store"), patch(
        "app.services.llm.check_ark_health", return_value=True
    ), patch("app.services.llm.check_ollama_health", return_value=True):
        client = TestClient(create_app())
        resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["components"]["database"]["status"] == "up"
    assert "latency_ms" in body["components"]["database"]


def test_health_degraded_when_vectorstore_down():
    with patch(
        "app.db.vectorstore.get_vector_store", side_effect=RuntimeError("boom")
    ):
        client = TestClient(create_app())
        resp = client.get("/health")
    body = resp.json()
    assert resp.status_code == 200
    assert body["status"] == "degraded"
    assert body["components"]["vectorstore"]["status"] == "down"


def test_health_llm_provider_component_reflects_configured_only():
    with patch("app.db.vectorstore.get_vector_store"):
        client = TestClient(create_app())
        resp = client.get("/health")
    body = resp.json()
    assert "provider" in body["components"]["llm_provider"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --project ../.. pytest tests/api/test_health_check.py -v`
Expected: FAIL — response has flat `mysql`/`chroma` keys, not `components`.

- [ ] **Step 3: Replace the HealthResponse model**

In `apps/luna-corpus/app/api/routes.py` (~line 122), replace:

```python
class HealthResponse(BaseModel):
    """Health check response."""

    status: str
    mysql: str
    chroma: str
    ollama: str
    ark: str
    llm_provider: str
```

with:

```python
class ComponentHealth(BaseModel):
    """Health status of a single dependency."""

    status: str  # up | down | not_configured
    latency_ms: float | None = None
    provider: str | None = None


class HealthResponse(BaseModel):
    """Health check response."""

    status: str  # ok | degraded
    components: dict[str, ComponentHealth]
```

- [ ] **Step 4: Rewrite the health_check handler**

Replace the whole `health_check` function body (line 1382 to end of function) with:

```python
async def health_check(db: Annotated[Session, Depends(get_db)]) -> HealthResponse:
    """Report per-component health (database, vectorstore, llm_provider)."""
    import time

    from app.db.vectorstore import get_vector_store
    from app.services.llm import (
        check_ark_health,
        check_doubao_health,
        check_ollama_health,
    )

    settings = get_settings()
    components: dict[str, ComponentHealth] = {}

    # Database
    start = time.perf_counter()
    try:
        db.execute(text("SELECT 1"))
        db.commit()
        components["database"] = ComponentHealth(
            status="up", latency_ms=round((time.perf_counter() - start) * 1000, 2)
        )
    except Exception:
        components["database"] = ComponentHealth(status="down")

    # Vector store
    start = time.perf_counter()
    try:
        get_vector_store()
        components["vectorstore"] = ComponentHealth(
            status="up", latency_ms=round((time.perf_counter() - start) * 1000, 2)
        )
    except Exception:
        components["vectorstore"] = ComponentHealth(status="down")

    # LLM provider — only the configured provider is probed.
    provider = settings.llm_provider.value
    check = {
        "ollama": check_ollama_health,
        "ark": check_ark_health,
        "doubao": check_doubao_health,
    }.get(provider)
    try:
        healthy = bool(check()) if check else False
        provider_status = "up" if healthy else "not_configured"
    except Exception:
        provider_status = "down"
    components["llm_provider"] = ComponentHealth(
        status=provider_status, provider=provider
    )

    overall = "ok"
    if (
        components["database"].status == "down"
        or components["vectorstore"].status == "down"
    ):
        overall = "degraded"

    return HealthResponse(status=overall, components=components)
```

Note: keep the `@router.get("/health", response_model=HealthResponse)` decorator line unchanged.

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run --project ../.. pytest tests/api/test_health_check.py -v`
Expected: PASS (3 tests).

- [ ] **Step 6: Check for other consumers of the old health shape**

Run: `grep -rn '"mysql"\|\.mysql\|health.*chroma' apps/luna-corpus/tests apps/luna-corpus/app`
Expected: no references to the removed flat fields other than what you updated. If `tests/test_main.py` or similar asserts old keys, update them to the new `components` shape.

- [ ] **Step 7: Commit**

```bash
git add apps/luna-corpus/app/api/routes.py apps/luna-corpus/tests/api/test_health_check.py
git commit -m "feat(corpus): component-differentiated health check"
```

---

### Task 10: Full-suite verification, lint, and env docs

**Files:**
- Modify: `apps/luna-corpus/.env.example` (document new settings)
- Modify: `apps/luna-corpus/README.md` (short observability note)

**Interfaces:** none produced; final integration gate.

- [ ] **Step 1: Add new settings to .env.example**

Append to `apps/luna-corpus/.env.example`:

```dotenv
# Observability
LOG_LEVEL=INFO
# LOG_FORMAT defaults to json in production, console otherwise
# LOG_FORMAT=console
METRICS_ENABLED=true
```

- [ ] **Step 2: Add a README observability note**

Add a section to `apps/luna-corpus/README.md` after "Local development":

```markdown
## Observability

- Structured logs (JSON in production, console otherwise) carry `request_id`, `user_id`, and `tenant_id` when available. Control with `LOG_LEVEL` and `LOG_FORMAT`.
- Prometheus metrics are exposed at `GET /metrics` (disable with `METRICS_ENABLED=false`). HTTP request counts/latency plus retrieval, embedding, LLM, and index-task timings are tracked.
- `GET /health` reports per-component status for `database`, `vectorstore`, and the configured `llm_provider`; overall status is `degraded` if the database or vector store is down.
```

- [ ] **Step 3: Run lint**

Run (from repo root): `pnpm nx run luna-corpus:lint`
Expected: PASS (no ruff violations). Fix any reported issues.

- [ ] **Step 4: Run the full test suite**

Run (from repo root): `pnpm nx run luna-corpus:test`
Expected: PASS — all tests green, including the new observability suite.

- [ ] **Step 5: Manual smoke check of /metrics and /health**

Run (from `apps/luna-corpus/`): `uv run python -c "from fastapi.testclient import TestClient; from app.main import create_app; c=TestClient(create_app()); print(c.get('/metrics').status_code); print(c.get('/health').json())"`
Expected: prints `200` and a health JSON with a `components` object.

- [ ] **Step 6: Commit**

```bash
git add apps/luna-corpus/.env.example apps/luna-corpus/README.md
git commit -m "docs(corpus): document observability settings"
```

---

## Deferred to a follow-up milestone (out of scope for M8 code layer)

- Dockerfile + docker-compose (API / MySQL / Chroma server) minimal topology.
- README deployment manual (dependencies, startup, worker, production).
- Backup/restore and vector-index rebuild runbook.
- OpenTelemetry tracing; Grafana dashboards and alerting.

## Self-Review Notes

**Spec coverage:**
- §3 structured logging → Tasks 2, 3, 4.
- §3.3 access log with request_id/user_id/tenant_id/path/status/latency → Task 6.
- §4 metrics (HTTP + business stages) + /metrics + rate-limit exempt + enable switch → Tasks 5, 6, 7, 8.
- §4.1 path_template high-cardinality collapse → Task 6 (`resolve_path_template`).
- §5 health check differentiation, configured-provider-only, degraded→200 → Task 9.
- §6 config (log_level/log_format/metrics_enabled) → Task 1.
- §7 error handling (observability never breaks request) → enforced in Tasks 5 (`finally`), 6 (try/except), 9 (per-component catch).
- §8 tests → each task ships its named test file.
- §9 acceptance criteria → validated in Task 10 smoke + full suite.

**Deferred items** match the spec's "明确不做" list.
