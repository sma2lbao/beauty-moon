# P0-M7 安全防护与审计 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an auditable action trail, per-identity API rate limiting, and hardened upload validation to the luna-corpus FastAPI service.

**Architecture:** A new `app/security/` package holds request-context + rate-limit + body-size middleware and an `AuditService`. A new `AuditLog` SQLAlchemy model (with Alembic migration) is the durable trail. Audit rows are written explicitly inside route handlers; rate limiting and body-size limits run as ASGI middleware; upload hardening extends the existing M5 `IngestionService`.

**Tech Stack:** Python 3.12, FastAPI, Starlette middleware, SQLAlchemy 2.0 (`Mapped`/`mapped_column`), Alembic, pytest, MySQL (CHAR(36) UUID PKs), SQLite for tests.

## Global Constraints

- Run all tasks via nx: `pnpm nx test luna-corpus` (or target a file with the project's pytest config). Never invoke pytest globally without the workspace package manager.
- UUID primary keys: `mapped_column(CHAR(36), primary_key=True, default=lambda: str(uuid.uuid4()))` — import `CHAR` from `sqlalchemy.dialects.mysql`.
- Timestamps: `mapped_column(DateTime, server_default=func.now())`.
- Enums backing string columns: subclass `(str, enum.Enum)`, store with `Mapped[...] = mapped_column(Enum(MyEnum), ...)`.
- Audit logging must NEVER break a request: failure-path writes swallow their own exceptions.
- Migration revision id format: `YYYYMMDD_NNNN`; new migration is `20260630_0006`, `down_revision = "20260629_0005"`.
- Config fields use pydantic `Field(default=..., description=...)` on the `Settings` class in `app/core/config.py`.
- Follow existing import ordering and docstring style (module docstring + Google-style arg docs).

---

## File Structure

- `app/core/config.py` — MODIFY: add rate-limit, body-size settings.
- `app/security/__init__.py` — CREATE: package marker.
- `app/security/context.py` — CREATE: contextvars for request_id/client_ip + accessors.
- `app/security/rate_limiter.py` — CREATE: in-process fixed-window limiter.
- `app/security/middleware.py` — CREATE: RequestContext, RateLimit, BodySizeLimit middleware.
- `app/security/audit.py` — CREATE: `AuditAction` enum + `AuditService`.
- `app/db/models.py` — MODIFY: add `AuditLog` model.
- `alembic/versions/20260630_0006_audit_logs.py` — CREATE: migration.
- `app/main.py` — MODIFY: register middleware.
- `app/api/routes.py` — MODIFY: instrument create/delete/index/qa handlers; harden nothing here.
- `app/services/ingestion/service.py` — MODIFY: empty-file + actual-byte size checks.
- `app/services/ingestion/exceptions.py` — MODIFY: add `EmptyFileError`.
- Tests under `tests/security/`, `tests/db/`, `tests/api/`, `tests/services/ingestion/`.

---

## Task 1: Config settings for rate limiting and body size

**Files:**
- Modify: `app/core/config.py`
- Test: `tests/core/test_config_security.py`

**Interfaces:**
- Produces: `Settings.rate_limit_enabled: bool`, `Settings.rate_limit_default_per_minute: int`, `Settings.rate_limit_qa_per_minute: int`, `Settings.rate_limit_upload_per_minute: int`, `Settings.max_json_body_size: int`.

- [ ] **Step 1: Write the failing test**

```python
# tests/core/test_config_security.py
"""Tests for security-related settings."""
from app.core.config import Settings


def test_security_settings_defaults():
    settings = Settings()
    assert settings.rate_limit_enabled is True
    assert settings.rate_limit_default_per_minute == 120
    assert settings.rate_limit_qa_per_minute == 30
    assert settings.rate_limit_upload_per_minute == 10
    assert settings.max_json_body_size == 1048576
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pnpm nx test luna-corpus -- tests/core/test_config_security.py -v`
Expected: FAIL with `AttributeError` on `rate_limit_enabled`.

- [ ] **Step 3: Add the settings**

Add to the `Settings` class in `app/core/config.py`, after the Ingestion / File Storage block (just before `@field_validator("cors_allow_origins", ...)`):

```python
    # Security / Rate limiting
    rate_limit_enabled: bool = Field(
        default=True,
        description="Enable in-process API rate limiting",
    )
    rate_limit_default_per_minute: int = Field(
        default=120,
        description="Default rate limit for API routes (requests per minute)",
    )
    rate_limit_qa_per_minute: int = Field(
        default=30,
        description="Rate limit for QA routes (requests per minute)",
    )
    rate_limit_upload_per_minute: int = Field(
        default=10,
        description="Rate limit for upload/process routes (requests per minute)",
    )
    max_json_body_size: int = Field(
        default=1048576,
        description="Maximum non-multipart request body size in bytes (1MB)",
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pnpm nx test luna-corpus -- tests/core/test_config_security.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/luna-corpus/app/core/config.py apps/luna-corpus/tests/core/test_config_security.py
git commit -m "feat(corpus): add rate-limit and body-size security settings"
```

---

## Task 2: Request context (contextvars + accessors)

**Files:**
- Create: `app/security/__init__.py`
- Create: `app/security/context.py`
- Test: `tests/security/test_context.py`

**Interfaces:**
- Produces:
  - `set_request_context(request_id: str, client_ip: str | None) -> None`
  - `get_request_id() -> str | None`
  - `get_client_ip() -> str | None`
  - `reset_request_context() -> None`

- [ ] **Step 1: Write the failing test**

```python
# tests/security/test_context.py
"""Tests for request-scoped security context."""
from app.security.context import (
    get_client_ip,
    get_request_id,
    reset_request_context,
    set_request_context,
)


def test_set_and_get_context():
    set_request_context("req-123", "10.0.0.1")
    assert get_request_id() == "req-123"
    assert get_client_ip() == "10.0.0.1"


def test_reset_clears_context():
    set_request_context("req-123", "10.0.0.1")
    reset_request_context()
    assert get_request_id() is None
    assert get_client_ip() is None


def test_defaults_are_none():
    reset_request_context()
    assert get_request_id() is None
    assert get_client_ip() is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pnpm nx test luna-corpus -- tests/security/test_context.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.security'`.

- [ ] **Step 3: Create the package and module**

Create `app/security/__init__.py`:

```python
"""Security: request context, rate limiting, body-size limits, audit."""
```

Create `app/security/context.py`:

```python
"""Request-scoped context for request_id and client IP via contextvars."""
from contextvars import ContextVar

_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)
_client_ip: ContextVar[str | None] = ContextVar("client_ip", default=None)


def set_request_context(request_id: str, client_ip: str | None) -> None:
    """Store request_id and client IP for the current request scope."""
    _request_id.set(request_id)
    _client_ip.set(client_ip)


def get_request_id() -> str | None:
    """Return the current request_id, or None if unset."""
    return _request_id.get()


def get_client_ip() -> str | None:
    """Return the current client IP, or None if unset."""
    return _client_ip.get()


def reset_request_context() -> None:
    """Clear the request context (request_id and client IP)."""
    _request_id.set(None)
    _client_ip.set(None)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pnpm nx test luna-corpus -- tests/security/test_context.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/luna-corpus/app/security/__init__.py apps/luna-corpus/app/security/context.py apps/luna-corpus/tests/security/test_context.py
git commit -m "feat(corpus): add request-scoped security context"
```

---

## Task 3: In-process rate limiter

**Files:**
- Create: `app/security/rate_limiter.py`
- Test: `tests/security/test_rate_limiter.py`

**Interfaces:**
- Produces:
  - `class RateLimiter:` with `__init__(self, now_fn: Callable[[], float] = time.monotonic)` and `check(self, key: str, limit_per_minute: int) -> bool` (returns `True` if allowed, `False` if over limit).
  - Fixed 60-second window keyed by `key`.

- [ ] **Step 1: Write the failing test**

```python
# tests/security/test_rate_limiter.py
"""Tests for the in-process rate limiter."""
from app.security.rate_limiter import RateLimiter


class FakeClock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def test_allows_under_limit():
    limiter = RateLimiter(now_fn=FakeClock())
    assert all(limiter.check("user-a", 3) for _ in range(3))


def test_blocks_over_limit():
    limiter = RateLimiter(now_fn=FakeClock())
    for _ in range(3):
        limiter.check("user-a", 3)
    assert limiter.check("user-a", 3) is False


def test_window_resets_after_60s():
    clock = FakeClock()
    limiter = RateLimiter(now_fn=clock)
    for _ in range(3):
        limiter.check("user-a", 3)
    assert limiter.check("user-a", 3) is False
    clock.t += 61
    assert limiter.check("user-a", 3) is True


def test_keys_are_independent():
    limiter = RateLimiter(now_fn=FakeClock())
    for _ in range(3):
        limiter.check("user-a", 3)
    assert limiter.check("user-b", 3) is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pnpm nx test luna-corpus -- tests/security/test_rate_limiter.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement the limiter**

Create `app/security/rate_limiter.py`:

```python
"""In-process fixed-window rate limiter.

Per-process state only; not shared across replicas. Multi-instance
correctness (Redis-backed) is a deferred M8/scale follow-up.
"""
import time
from collections.abc import Callable

_WINDOW_SECONDS = 60.0


class RateLimiter:
    """Fixed 60-second window counter keyed by an arbitrary string."""

    def __init__(self, now_fn: Callable[[], float] = time.monotonic) -> None:
        self._now = now_fn
        # key -> (window_start, count)
        self._windows: dict[str, tuple[float, int]] = {}

    def check(self, key: str, limit_per_minute: int) -> bool:
        """Record a hit for key; return True if within limit, else False."""
        now = self._now()
        window_start, count = self._windows.get(key, (now, 0))
        if now - window_start >= _WINDOW_SECONDS:
            window_start, count = now, 0
        count += 1
        self._windows[key] = (window_start, count)
        return count <= limit_per_minute
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pnpm nx test luna-corpus -- tests/security/test_rate_limiter.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add apps/luna-corpus/app/security/rate_limiter.py apps/luna-corpus/tests/security/test_rate_limiter.py
git commit -m "feat(corpus): add in-process fixed-window rate limiter"
```

---

## Task 4: Security middleware (request context, rate limit, body size)

**Files:**
- Create: `app/security/middleware.py`
- Test: `tests/security/test_middleware.py`

**Interfaces:**
- Consumes: `app.security.context.set_request_context/reset_request_context`, `app.security.rate_limiter.RateLimiter`, `app.core.config.get_settings`.
- Produces three Starlette `BaseHTTPMiddleware` subclasses:
  - `RequestContextMiddleware` — sets `request_id` (honors incoming `X-Request-Id`, else generates uuid4), client IP (first `X-Forwarded-For` entry if present, else `request.client.host`); adds `X-Request-Id` to the response; clears context after.
  - `RateLimitMiddleware(app, limiter: RateLimiter)` — resolves category from path, returns `JSONResponse(status_code=429, headers={"Retry-After": "60"})` when over limit; skips `/` and `/health`.
  - `BodySizeLimitMiddleware` — for non-multipart requests with a body larger than `settings.max_json_body_size`, returns `JSONResponse(status_code=413)`.
  - Helper `resolve_category(path: str) -> str` returning `"qa"`, `"upload"`, or `"default"`.

- [ ] **Step 1: Write the failing test**

```python
# tests/security/test_middleware.py
"""Tests for security middleware: request context, rate limit, body size."""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.security.middleware import (
    BodySizeLimitMiddleware,
    RateLimitMiddleware,
    RequestContextMiddleware,
    resolve_category,
)
from app.security.rate_limiter import RateLimiter


def _build_app(limiter: RateLimiter, max_body: int = 1048576) -> FastAPI:
    app = FastAPI()
    app.add_middleware(RateLimitMiddleware, limiter=limiter)
    app.add_middleware(BodySizeLimitMiddleware, max_body_size=max_body)
    app.add_middleware(RequestContextMiddleware)

    @app.post("/qa/query")
    async def qa():
        return {"ok": True}

    @app.get("/")
    async def root():
        return {"ok": True}

    return app


def test_resolve_category():
    assert resolve_category("/qa/query") == "qa"
    assert resolve_category("/qa/stream") == "qa"
    assert resolve_category("/files/upload") == "upload"
    assert resolve_category("/documents/abc/process") == "upload"
    assert resolve_category("/documents") == "default"


def test_request_id_generated_and_returned():
    client = TestClient(_build_app(RateLimiter()))
    resp = client.get("/")
    assert resp.status_code == 200
    assert resp.headers.get("X-Request-Id")


def test_request_id_honored_from_header():
    client = TestClient(_build_app(RateLimiter()))
    resp = client.get("/", headers={"X-Request-Id": "incoming-123"})
    assert resp.headers["X-Request-Id"] == "incoming-123"


def test_rate_limit_returns_429_with_retry_after():
    # qa category limit comes from settings; force a tiny limit via many calls.
    from app.core.config import get_settings

    limiter = RateLimiter()
    client = TestClient(_build_app(limiter))
    limit = get_settings().rate_limit_qa_per_minute
    last = None
    for _ in range(limit + 1):
        last = client.post("/qa/query")
    assert last.status_code == 429
    assert last.headers["Retry-After"] == "60"


def test_root_path_not_rate_limited():
    limiter = RateLimiter()
    client = TestClient(_build_app(limiter))
    for _ in range(200):
        resp = client.get("/")
    assert resp.status_code == 200


def test_body_size_limit_returns_413():
    client = TestClient(_build_app(RateLimiter(), max_body=10))
    resp = client.post("/qa/query", content=b"x" * 50)
    assert resp.status_code == 413
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pnpm nx test luna-corpus -- tests/security/test_middleware.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement the middleware**

Create `app/security/middleware.py`:

```python
"""ASGI middleware: request context, rate limiting, body-size limits."""
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.config import get_settings
from app.security.context import reset_request_context, set_request_context
from app.security.rate_limiter import RateLimiter

_RATE_LIMIT_EXEMPT = {"/", "/health"}


def resolve_category(path: str) -> str:
    """Map a request path to a rate-limit category."""
    if path.startswith("/qa/"):
        return "qa"
    if path == "/files/upload" or (
        path.startswith("/documents/") and path.endswith("/process")
    ):
        return "upload"
    return "default"


def _client_ip(request: Request) -> str | None:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Generate/propagate request_id and capture client IP."""

    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = request.headers.get("X-Request-Id") or str(uuid.uuid4())
        set_request_context(request_id, _client_ip(request))
        try:
            response = await call_next(request)
        finally:
            reset_request_context()
        response.headers["X-Request-Id"] = request_id
        return response


class BodySizeLimitMiddleware(BaseHTTPMiddleware):
    """Reject oversized non-multipart request bodies with 413."""

    def __init__(self, app, max_body_size: int | None = None) -> None:
        super().__init__(app)
        self._max_body_size = max_body_size

    async def dispatch(self, request: Request, call_next) -> Response:
        max_size = (
            self._max_body_size
            if self._max_body_size is not None
            else get_settings().max_json_body_size
        )
        content_type = request.headers.get("content-type", "")
        if not content_type.startswith("multipart/"):
            body = await request.body()
            if len(body) > max_size:
                return JSONResponse(
                    status_code=413,
                    content={"detail": "Request body too large"},
                )
        return await call_next(request)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Per-identity, per-category fixed-window rate limiting."""

    def __init__(self, app, limiter: RateLimiter | None = None) -> None:
        super().__init__(app)
        self._limiter = limiter or RateLimiter()

    async def dispatch(self, request: Request, call_next) -> Response:
        settings = get_settings()
        if not settings.rate_limit_enabled or request.url.path in _RATE_LIMIT_EXEMPT:
            return await call_next(request)

        category = resolve_category(request.url.path)
        limit = {
            "qa": settings.rate_limit_qa_per_minute,
            "upload": settings.rate_limit_upload_per_minute,
        }.get(category, settings.rate_limit_default_per_minute)

        identity = request.headers.get("X-User-Id") or (
            request.client.host if request.client else "anonymous"
        )
        key = f"{identity}:{category}"
        if not self._limiter.check(key, limit):
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded"},
                headers={"Retry-After": "60"},
            )
        return await call_next(request)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pnpm nx test luna-corpus -- tests/security/test_middleware.py -v`
Expected: PASS (7 tests).

- [ ] **Step 5: Commit**

```bash
git add apps/luna-corpus/app/security/middleware.py apps/luna-corpus/tests/security/test_middleware.py
git commit -m "feat(corpus): add request-context, rate-limit, body-size middleware"
```

---

## Task 5: Register middleware in the app

**Files:**
- Modify: `app/main.py`
- Test: `tests/api/test_middleware_wiring.py`

**Interfaces:**
- Consumes: middleware classes from Task 4.
- Middleware add order so the effective outer→inner chain is RequestContext → BodySizeLimit → RateLimit → CORS. (Starlette applies `add_middleware` in reverse, so add CORS first, then RateLimit, then BodySizeLimit, then RequestContext last.)

- [ ] **Step 1: Write the failing test**

```python
# tests/api/test_middleware_wiring.py
"""Verify security middleware is wired into the app."""
from app.main import create_app
from app.security.middleware import (
    BodySizeLimitMiddleware,
    RateLimitMiddleware,
    RequestContextMiddleware,
)


def test_security_middleware_registered():
    app = create_app()
    classes = {m.cls for m in app.user_middleware}
    assert RequestContextMiddleware in classes
    assert RateLimitMiddleware in classes
    assert BodySizeLimitMiddleware in classes


def test_request_id_header_present_on_root():
    from fastapi.testclient import TestClient

    client = TestClient(create_app())
    resp = client.get("/")
    assert resp.headers.get("X-Request-Id")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pnpm nx test luna-corpus -- tests/api/test_middleware_wiring.py -v`
Expected: FAIL — middleware not registered.

- [ ] **Step 3: Wire middleware into `create_app`**

In `app/main.py`, add the import near the other app imports:

```python
from app.security.middleware import (
    BodySizeLimitMiddleware,
    RateLimitMiddleware,
    RequestContextMiddleware,
)
```

In `create_app`, replace the existing CORS `add_middleware` block with the following (CORS added first so it ends up innermost relative to the security layers; RequestContext added last so it is outermost):

```python
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allow_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(RateLimitMiddleware)
    app.add_middleware(BodySizeLimitMiddleware)
    app.add_middleware(RequestContextMiddleware)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pnpm nx test luna-corpus -- tests/api/test_middleware_wiring.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Run the existing API suite to confirm no regressions**

Run: `pnpm nx test luna-corpus -- tests/api -v`
Expected: PASS (existing tests still green).

- [ ] **Step 6: Commit**

```bash
git add apps/luna-corpus/app/main.py apps/luna-corpus/tests/api/test_middleware_wiring.py
git commit -m "feat(corpus): register security middleware in app"
```

---

## Task 6: AuditLog model

**Files:**
- Modify: `app/db/models.py`
- Test: `tests/db/test_audit_log_model.py`

**Interfaces:**
- Produces:
  - `class AuditAction(str, enum.Enum)` is defined in `app/security/audit.py` (Task 8) — the model stores `action` as a plain `String(100)` to avoid coupling the DB layer to the enum.
  - `class AuditResult(str, enum.Enum)` with `SUCCESS = "success"`, `FAILURE = "failure"` — defined here in models.
  - `class AuditLog(Base)` table `audit_logs` with columns: `id`, `actor_user_id` (FK users, nullable), `tenant_id`/`workspace_id`/`knowledge_base_id` (nullable String(36)), `action` (String(100)), `resource_type` (String(50)), `resource_id` (String(36) nullable), `result` (Enum(AuditResult)), `detail` (Text nullable), `request_id` (String(64) nullable), `client_ip` (String(64) nullable), `created_at`.

- [ ] **Step 1: Write the failing test**

```python
# tests/db/test_audit_log_model.py
"""Tests for the AuditLog model."""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models import AuditLog, AuditResult, Base


def _session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def test_audit_log_persists_all_fields():
    session = _session()
    log = AuditLog(
        actor_user_id="user-1",
        tenant_id="t-1",
        workspace_id="w-1",
        knowledge_base_id="kb-1",
        action="document.create",
        resource_type="document",
        resource_id="doc-1",
        result=AuditResult.SUCCESS,
        detail=None,
        request_id="req-1",
        client_ip="10.0.0.1",
    )
    session.add(log)
    session.commit()
    session.refresh(log)
    assert log.id is not None
    assert log.created_at is not None
    assert log.result == AuditResult.SUCCESS


def test_audit_log_nullable_actor_and_resource():
    session = _session()
    log = AuditLog(
        action="qa.query",
        resource_type="conversation",
        result=AuditResult.FAILURE,
        detail="boom",
    )
    session.add(log)
    session.commit()
    session.refresh(log)
    assert log.actor_user_id is None
    assert log.resource_id is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pnpm nx test luna-corpus -- tests/db/test_audit_log_model.py -v`
Expected: FAIL with `ImportError` on `AuditLog`/`AuditResult`.

- [ ] **Step 3: Add the model**

In `app/db/models.py`, add an enum near the other enums (after `MessageRole`):

```python
class AuditResult(str, enum.Enum):
    """Outcome of an audited action."""

    SUCCESS = "success"
    FAILURE = "failure"
```

Add the model at the end of the file:

```python
class AuditLog(Base):
    """Durable, queryable audit trail for security-relevant actions."""

    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(
        CHAR(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    actor_user_id: Mapped[str | None] = mapped_column(
        CHAR(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    tenant_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    workspace_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    knowledge_base_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(50), nullable=False)
    resource_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    result: Mapped[AuditResult] = mapped_column(Enum(AuditResult), nullable=False)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    client_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pnpm nx test luna-corpus -- tests/db/test_audit_log_model.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add apps/luna-corpus/app/db/models.py apps/luna-corpus/tests/db/test_audit_log_model.py
git commit -m "feat(corpus): add AuditLog model and AuditResult enum"
```

---

## Task 7: Alembic migration for audit_logs

**Files:**
- Create: `alembic/versions/20260630_0006_audit_logs.py`

**Interfaces:**
- Consumes: `down_revision = "20260629_0005"`.

- [ ] **Step 1: Create the migration**

Create `alembic/versions/20260630_0006_audit_logs.py`:

```python
"""add audit_logs table

Revision ID: 20260630_0006
Revises: 20260629_0005
Create Date: 2026-06-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import mysql

from alembic import op

revision: str = "20260630_0006"
down_revision: str | None = "20260629_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "audit_logs",
        sa.Column("id", mysql.CHAR(36), nullable=False),
        sa.Column("actor_user_id", mysql.CHAR(36), nullable=True),
        sa.Column("tenant_id", sa.String(36), nullable=True),
        sa.Column("workspace_id", sa.String(36), nullable=True),
        sa.Column("knowledge_base_id", sa.String(36), nullable=True),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("resource_type", sa.String(50), nullable=False),
        sa.Column("resource_id", sa.String(36), nullable=True),
        sa.Column(
            "result",
            sa.Enum("success", "failure", name="auditresult"),
            nullable=False,
        ),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("request_id", sa.String(64), nullable=True),
        sa.Column("client_ip", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("NOW()")),
        sa.ForeignKeyConstraint(
            ["actor_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("audit_logs")
    op.execute("DROP TYPE IF EXISTS auditresult")
```

- [ ] **Step 2: Verify migration imports cleanly**

Run: `pnpm nx run luna-corpus:lint` (or `python -c "import ast; ast.parse(open('apps/luna-corpus/alembic/versions/20260630_0006_audit_logs.py').read())"`)
Expected: no syntax/lint errors.

- [ ] **Step 3: Commit**

```bash
git add apps/luna-corpus/alembic/versions/20260630_0006_audit_logs.py
git commit -m "feat(corpus): add alembic migration for audit_logs table"
```

---

## Task 8: AuditService and AuditAction

**Files:**
- Create: `app/security/audit.py`
- Test: `tests/security/test_audit_service.py`

**Interfaces:**
- Consumes: `app.db.models.AuditLog/AuditResult`, `app.db.database.SessionLocal`, `app.security.context.get_request_id/get_client_ip`, `app.api.auth.AuthenticatedRequestContext`.
- Produces:
  - `class AuditAction(str, enum.Enum)` with `DOCUMENT_CREATE = "document.create"`, `DOCUMENT_DELETE = "document.delete"`, `DOCUMENT_INDEX = "document.index"`, `QA_QUERY = "qa.query"`.
  - `class AuditService:`
    - `record(db, *, action: AuditAction, resource_type: str, resource_id: str | None, result: AuditResult, context=None, detail: str | None = None) -> AuditLog` — builds an `AuditLog` from `context` (if given) + contextvars, `db.add(...)`, `db.flush()` (caller commits with the action). Returns the row.
    - `record_failure(*, action, resource_type, resource_id, context=None, detail=None) -> None` — opens its own `SessionLocal()`, writes a `FAILURE` row, commits, closes; swallows and logs any exception.

- [ ] **Step 1: Write the failing test**

```python
# tests/security/test_audit_service.py
"""Tests for AuditService."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models import AuditLog, AuditResult, Base
from app.security.audit import AuditAction, AuditService
from app.security.context import reset_request_context, set_request_context


@pytest.fixture
def Session(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    maker = sessionmaker(bind=engine)
    monkeypatch.setattr("app.security.audit.SessionLocal", maker)
    return maker


def test_record_writes_row_with_context(Session):
    set_request_context("req-9", "1.2.3.4")
    db = Session()
    service = AuditService()
    service.record(
        db,
        action=AuditAction.DOCUMENT_CREATE,
        resource_type="document",
        resource_id="doc-1",
        result=AuditResult.SUCCESS,
    )
    db.commit()
    reset_request_context()
    row = db.query(AuditLog).one()
    assert row.action == "document.create"
    assert row.request_id == "req-9"
    assert row.client_ip == "1.2.3.4"
    assert row.result == AuditResult.SUCCESS


def test_record_not_committed_until_caller_commits(Session):
    db = Session()
    AuditService().record(
        db,
        action=AuditAction.DOCUMENT_CREATE,
        resource_type="document",
        resource_id="doc-1",
        result=AuditResult.SUCCESS,
    )
    db.rollback()
    assert db.query(AuditLog).count() == 0


def test_record_failure_survives_independently(Session):
    AuditService().record_failure(
        action=AuditAction.DOCUMENT_DELETE,
        resource_type="document",
        resource_id="doc-x",
        detail="not found",
    )
    verify = Session()
    row = verify.query(AuditLog).one()
    assert row.result == AuditResult.FAILURE
    assert row.detail == "not found"


def test_record_failure_swallows_errors(monkeypatch):
    # SessionLocal raising must not propagate.
    def boom():
        raise RuntimeError("db down")

    monkeypatch.setattr("app.security.audit.SessionLocal", boom)
    AuditService().record_failure(
        action=AuditAction.QA_QUERY,
        resource_type="conversation",
        resource_id=None,
        detail="x",
    )  # must not raise
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pnpm nx test luna-corpus -- tests/security/test_audit_service.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement AuditService**

Create `app/security/audit.py`:

```python
"""Audit logging service and action vocabulary."""
import enum
import logging

from sqlalchemy.orm import Session

from app.db.database import SessionLocal
from app.db.models import AuditLog, AuditResult
from app.security.context import get_client_ip, get_request_id

logger = logging.getLogger(__name__)


class AuditAction(str, enum.Enum):
    """Audited action vocabulary."""

    DOCUMENT_CREATE = "document.create"
    DOCUMENT_DELETE = "document.delete"
    DOCUMENT_INDEX = "document.index"
    QA_QUERY = "qa.query"


def _scope(context):
    if context is None:
        return None, None, None, None
    return (
        getattr(context.user, "id", None),
        getattr(context.tenant, "id", None),
        getattr(context.workspace, "id", None),
        getattr(context.knowledge_base, "id", None),
    )


class AuditService:
    """Writes audit rows. Success rows share the caller's transaction;
    failure rows are committed in an independent session."""

    def record(
        self,
        db: Session,
        *,
        action: "AuditAction",
        resource_type: str,
        resource_id: str | None,
        result: AuditResult,
        context=None,
        detail: str | None = None,
    ) -> AuditLog:
        """Add an audit row to the caller's session (caller commits)."""
        actor_id, tenant_id, workspace_id, kb_id = _scope(context)
        row = AuditLog(
            actor_user_id=actor_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            knowledge_base_id=kb_id,
            action=action.value,
            resource_type=resource_type,
            resource_id=resource_id,
            result=result,
            detail=detail,
            request_id=get_request_id(),
            client_ip=get_client_ip(),
        )
        db.add(row)
        db.flush()
        return row

    def record_failure(
        self,
        *,
        action: "AuditAction",
        resource_type: str,
        resource_id: str | None,
        context=None,
        detail: str | None = None,
    ) -> None:
        """Write a FAILURE row in an independent session; never raises."""
        try:
            db = SessionLocal()
            try:
                self.record(
                    db,
                    action=action,
                    resource_type=resource_type,
                    resource_id=resource_id,
                    result=AuditResult.FAILURE,
                    context=context,
                    detail=detail,
                )
                db.commit()
            finally:
                db.close()
        except Exception:  # noqa: BLE001 - auditing must never break a request
            logger.exception("Failed to write failure audit log")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pnpm nx test luna-corpus -- tests/security/test_audit_service.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add apps/luna-corpus/app/security/audit.py apps/luna-corpus/tests/security/test_audit_service.py
git commit -m "feat(corpus): add AuditService and AuditAction vocabulary"
```

---

## Task 9: Instrument document create/delete handlers

**Files:**
- Modify: `app/api/routes.py` (`create_document` ~line 372, `delete_document` ~line 506)
- Test: `tests/api/test_audit_integration.py`

**Interfaces:**
- Consumes: `AuditService`, `AuditAction`, `AuditResult`.
- In `create_document`: after `db.add(db_doc)` / before final `db.commit()`, call `AuditService().record(db, action=DOCUMENT_CREATE, resource_type="document", resource_id=db_doc.id, result=SUCCESS, context=context)`, then commit once.
- In `delete_document`: on the `not doc` branch call `record_failure(...)` then raise 404; on success call `record(...)` before the single `db.commit()`.

- [ ] **Step 1: Write the failing test**

```python
# tests/api/test_audit_integration.py
"""Integration tests: audited actions produce audit rows."""
from unittest.mock import patch

from app.auth.permissions import PermissionSlug
from app.db.models import AuditLog, AuditResult, Document
from tests.api.test_file_upload import (
    _auth_headers,
    app_db,
    client,
    create_user_with_permissions,
)


def test_create_document_writes_audit(client, app_db):
    _, Session, context = app_db
    user_id = create_user_with_permissions(
        Session,
        context["workspace_id"],
        "writer",
        [PermissionSlug.DOCUMENT_WRITE, PermissionSlug.WORKSPACE_READ,
         PermissionSlug.KNOWLEDGE_BASE_READ],
    )
    headers = _auth_headers(
        context, knowledge_base_id=context["kb_one_id"], user_id=user_id
    )
    resp = client.post(
        "/documents",
        json={"title": "T", "content": "hello", "source": "test"},
        headers=headers,
    )
    assert resp.status_code == 200
    session = Session()
    row = session.query(AuditLog).filter(AuditLog.action == "document.create").one()
    assert row.result == AuditResult.SUCCESS
    assert row.actor_user_id == user_id
    assert row.resource_id == resp.json()["id"]


def test_delete_missing_document_writes_failure_audit(client, app_db):
    _, Session, context = app_db
    user_id = create_user_with_permissions(
        Session,
        context["workspace_id"],
        "deleter",
        [PermissionSlug.DOCUMENT_DELETE, PermissionSlug.WORKSPACE_READ,
         PermissionSlug.KNOWLEDGE_BASE_READ],
    )
    headers = _auth_headers(
        context, knowledge_base_id=context["kb_one_id"], user_id=user_id
    )
    resp = client.delete("/documents/does-not-exist", headers=headers)
    assert resp.status_code == 404
    session = Session()
    row = session.query(AuditLog).filter(AuditLog.action == "document.delete").one()
    assert row.result == AuditResult.FAILURE
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pnpm nx test luna-corpus -- tests/api/test_audit_integration.py -v`
Expected: FAIL — no audit rows written.

- [ ] **Step 3: Add the import**

In `app/api/routes.py`, add near the top-level imports:

```python
from app.security.audit import AuditAction, AuditService
from app.db.models import AuditResult
```

(If `AuditResult` cannot be merged into an existing `from app.db.models import (...)` block, add it there instead to satisfy lint.)

- [ ] **Step 4: Instrument `create_document`**

Replace the `db.add(db_doc)` / `db.commit()` / `db.refresh(db_doc)` block with:

```python
    db.add(db_doc)
    db.flush()
    AuditService().record(
        db,
        action=AuditAction.DOCUMENT_CREATE,
        resource_type="document",
        resource_id=db_doc.id,
        result=AuditResult.SUCCESS,
        context=context,
    )
    db.commit()
    db.refresh(db_doc)
```

- [ ] **Step 5: Instrument `delete_document`**

Replace the `if not doc:` block and the trailing delete/commit with:

```python
    if not doc:
        AuditService().record_failure(
            action=AuditAction.DOCUMENT_DELETE,
            resource_type="document",
            resource_id=document_id,
            context=context,
            detail="not found",
        )
        raise HTTPException(status_code=404, detail="Document not found")

    db.delete(doc)
    AuditService().record(
        db,
        action=AuditAction.DOCUMENT_DELETE,
        resource_type="document",
        resource_id=document_id,
        result=AuditResult.SUCCESS,
        context=context,
    )
    db.commit()
```

- [ ] **Step 6: Run test to verify it passes**

Run: `pnpm nx test luna-corpus -- tests/api/test_audit_integration.py -v`
Expected: PASS (2 tests).

- [ ] **Step 7: Commit**

```bash
git add apps/luna-corpus/app/api/routes.py apps/luna-corpus/tests/api/test_audit_integration.py
git commit -m "feat(corpus): audit document create and delete actions"
```

---

## Task 10: Instrument QA query and the background index task

**Files:**
- Modify: `app/api/routes.py` (`query` ~line 280, `_run_index_task` ~line 254)
- Test: `tests/api/test_audit_qa_index.py`

**Interfaces:**
- Consumes: `AuditService`, `AuditAction`, `AuditResult`, `get_db`, `SessionLocal`.
- `query`: add `db: Annotated[Session, Depends(get_db)]` parameter; after computing `result`, record `QA_QUERY` success (resource_type `"knowledge_base"`, resource_id = `context.knowledge_base.id`) and `db.commit()`.
- `_run_index_task`: on success record `DOCUMENT_INDEX`/SUCCESS in the same `db` before its commit path; on exception use `record_failure` (independent session) with `DOCUMENT_INDEX`. No `context` available here, so pass `context=None` and include `resource_id=document_id`.

- [ ] **Step 1: Write the failing test**

```python
# tests/api/test_audit_qa_index.py
"""Audit coverage for QA query and background index task."""
from unittest.mock import patch

from app.auth.permissions import PermissionSlug
from app.db.models import AuditLog, AuditResult
from tests.api.test_file_upload import (
    _auth_headers,
    app_db,
    client,
    create_user_with_permissions,
)


@patch("app.api.routes.answer_question")
def test_qa_query_writes_audit(mock_answer, client, app_db):
    mock_answer.return_value = {
        "answer": "hi",
        "sources": [],
        "processing_time_ms": 5,
    }
    _, Session, context = app_db
    user_id = create_user_with_permissions(
        Session,
        context["workspace_id"],
        "asker",
        [PermissionSlug.QA_QUERY, PermissionSlug.WORKSPACE_READ,
         PermissionSlug.KNOWLEDGE_BASE_READ],
    )
    headers = _auth_headers(
        context, knowledge_base_id=context["kb_one_id"], user_id=user_id
    )
    resp = client.post("/qa/query", json={"question": "what?"}, headers=headers)
    assert resp.status_code == 200
    session = Session()
    row = session.query(AuditLog).filter(AuditLog.action == "qa.query").one()
    assert row.result == AuditResult.SUCCESS
    assert row.actor_user_id == user_id


def test_index_task_writes_success_audit(app_db, monkeypatch):
    engine, Session, context = app_db
    monkeypatch.setattr("app.api.routes.SessionLocal", Session)

    from app.db.models import Document
    from app.api.routes import _run_index_task

    session = Session()
    doc = Document(title="d", content="c", knowledge_base_id=context["kb_one_id"])
    session.add(doc)
    session.commit()
    doc_id = doc.id

    with patch("app.services.document_processor.DocumentProcessor") as proc, \
         patch("app.api.routes.TaskService") as task_service:
        proc.return_value.process_document.return_value = None
        task_service.return_value.mark_running.return_value = None
        task_service.return_value.mark_completed.return_value = None
        _run_index_task("task-1", doc_id)

    verify = Session()
    row = (
        verify.query(AuditLog)
        .filter(AuditLog.action == "document.index")
        .one()
    )
    assert row.result == AuditResult.SUCCESS
    assert row.resource_id == doc_id
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pnpm nx test luna-corpus -- tests/api/test_audit_qa_index.py -v`
Expected: FAIL — no audit rows.

- [ ] **Step 3: Instrument `query`**

Change the `query` signature to add a db dependency (insert as the first parameter after `question_req`):

```python
async def query(
    question_req: QuestionRequest,
    db: Annotated[Session, Depends(get_db)],
    context: Annotated[
        AuthenticatedRequestContext,
        Depends(require_permission(PermissionSlug.QA_QUERY)),
    ],
) -> AnswerResponse:
```

Before the final `return AnswerResponse(...)`, add:

```python
    AuditService().record(
        db,
        action=AuditAction.QA_QUERY,
        resource_type="knowledge_base",
        resource_id=context.knowledge_base.id,
        result=AuditResult.SUCCESS,
        context=context,
    )
    db.commit()
```

- [ ] **Step 4: Instrument `_run_index_task`**

Replace the body of `_run_index_task` with:

```python
def _run_index_task(task_id: str, document_id: str) -> None:
    """Background task: chunk, embed, and vectorize a document.

    Runs in its own DB session. Catches all exceptions and updates
    task status accordingly.
    """
    from app.services.document_processor import DocumentProcessor

    db = SessionLocal()
    try:
        task_service = TaskService()
        task_service.mark_running(db, task_id)

        processor = DocumentProcessor()
        processor.process_document(db, document_id)

        task_service.mark_completed(db, task_id)
        AuditService().record(
            db,
            action=AuditAction.DOCUMENT_INDEX,
            resource_type="document",
            resource_id=document_id,
            result=AuditResult.SUCCESS,
            context=None,
        )
        db.commit()
    except Exception as e:
        task_service = TaskService()
        task_service.mark_failed(db, task_id, error_message=str(e))
        AuditService().record_failure(
            action=AuditAction.DOCUMENT_INDEX,
            resource_type="document",
            resource_id=document_id,
            context=None,
            detail=str(e),
        )
    finally:
        db.close()
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pnpm nx test luna-corpus -- tests/api/test_audit_qa_index.py -v`
Expected: PASS (2 tests).

- [ ] **Step 6: Run the full API + security suites for regressions**

Run: `pnpm nx test luna-corpus -- tests/api tests/security -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add apps/luna-corpus/app/api/routes.py apps/luna-corpus/tests/api/test_audit_qa_index.py
git commit -m "feat(corpus): audit qa query and background index task"
```

---

## Task 11: Upload hardening — empty file + actual-byte size

**Files:**
- Modify: `app/services/ingestion/exceptions.py`
- Modify: `app/services/ingestion/service.py` (~lines 99-117)
- Modify: `app/api/routes.py` (`upload_file` exception mapping ~line 1037)
- Test: `tests/services/ingestion/test_upload_hardening.py`

**Interfaces:**
- Produces: `class EmptyFileError(IngestionError)`.
- `ingest_file` raises `EmptyFileError` for zero-byte content; raises `HTTPException(413)` when `len(content) > max_upload_size` even if `file.size` is falsy.
- `upload_file` maps `EmptyFileError` → HTTP 422.

- [ ] **Step 1: Write the failing test**

```python
# tests/services/ingestion/test_upload_hardening.py
"""Tests for upload hardening: empty file and actual-byte size."""
import io

import pytest
from fastapi import HTTPException, UploadFile

from app.services.ingestion.exceptions import EmptyFileError
from app.services.ingestion.service import IngestionService


class _Registry:
    def is_supported(self, mime_type):
        return True

    def list_supported_types(self):
        return ["text/plain"]


def _upload(content: bytes, size, content_type="text/plain"):
    file = UploadFile(filename="f.txt", file=io.BytesIO(content))
    file.size = size  # may be None or spoofed
    file.headers = {"content-type": content_type}
    return file


@pytest.mark.asyncio
async def test_empty_file_rejected():
    service = IngestionService(
        storage=object(), parser_registry=_Registry(), max_upload_size=1000
    )
    with pytest.raises(EmptyFileError):
        await service.ingest_file(db=None, file=_upload(b"", size=0), knowledge_base_id="kb")


@pytest.mark.asyncio
async def test_actual_bytes_exceed_limit_when_size_missing():
    service = IngestionService(
        storage=object(), parser_registry=_Registry(), max_upload_size=5
    )
    with pytest.raises(HTTPException) as exc:
        await service.ingest_file(
            db=None, file=_upload(b"x" * 50, size=None), knowledge_base_id="kb"
        )
    assert exc.value.status_code == 413
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pnpm nx test luna-corpus -- tests/services/ingestion/test_upload_hardening.py -v`
Expected: FAIL — `EmptyFileError` does not exist / no 413 for missing size.

- [ ] **Step 3: Add the exception**

Append to `app/services/ingestion/exceptions.py`:

```python
class EmptyFileError(IngestionError):
    """Raised when an uploaded file has zero bytes."""

    pass
```

- [ ] **Step 4: Add the checks in `ingest_file`**

In `app/services/ingestion/service.py`, import the new exception in the existing `from app.services.ingestion.exceptions import (...)` block:

```python
    EmptyFileError,
```

Then, right after `content = file.file.read()` and `file.file.seek(0)` (the read block), insert:

```python
        # Reject empty files
        if len(content) == 0:
            raise EmptyFileError("Uploaded file is empty")

        # Enforce actual-byte size (defends against missing/spoofed Content-Length)
        if len(content) > self.max_upload_size:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail=f"File too large. Maximum size: {self.max_upload_size} bytes",
            )
```

(`HTTPException` and `status` are already imported in this module.)

- [ ] **Step 5: Map the exception in `upload_file`**

In `app/api/routes.py` `upload_file`, add an `except` clause alongside the existing `UnsupportedFileTypeError` handler. First add `EmptyFileError` to the ingestion exception imports, then:

```python
    except EmptyFileError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
        ) from e
```

- [ ] **Step 6: Run test to verify it passes**

Run: `pnpm nx test luna-corpus -- tests/services/ingestion/test_upload_hardening.py -v`
Expected: PASS (2 tests).

- [ ] **Step 7: Run the ingestion + upload API suites for regressions**

Run: `pnpm nx test luna-corpus -- tests/services/ingestion tests/api/test_file_upload.py -v`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add apps/luna-corpus/app/services/ingestion/exceptions.py apps/luna-corpus/app/services/ingestion/service.py apps/luna-corpus/app/api/routes.py apps/luna-corpus/tests/services/ingestion/test_upload_hardening.py
git commit -m "feat(corpus): harden uploads against empty and oversized files"
```

---

## Task 12: Full suite + lint gate

**Files:** none (verification only)

- [ ] **Step 1: Run the full test suite**

Run: `pnpm nx test luna-corpus`
Expected: all tests PASS.

- [ ] **Step 2: Run lint**

Run: `pnpm nx lint luna-corpus`
Expected: no ruff violations.

- [ ] **Step 3: Fix any lint/test issues inline, then commit if changes were made**

```bash
git add -A
git commit -m "chore(corpus): lint and test fixes for P0-M7"
```

---

## Self-Review Notes

- **Spec coverage:** rate limit 429 (Tasks 3-5), body-size 413 (Tasks 4-5), upload type 415 (existing M5) + size 413 + empty 422 (Task 11), audit table + service (Tasks 6-8), audited create/delete/index/qa (Tasks 9-10), request_id/IP plumbing (Task 2), success-in-transaction vs failure-independent semantics (Task 8 tests). Deferred items (prompt injection, PII, 403 audit, magic-byte, Redis) are explicitly out of scope per the spec.
- **Type consistency:** `AuditService.record(...)`/`record_failure(...)`, `AuditAction`, `AuditResult`, `RateLimiter.check(key, limit_per_minute)`, `resolve_category(path)` names match across tasks.
- **Note for executor:** `query` currently has no `db` param — Task 10 adds it; keep the existing parameter order valid (non-default params before defaults). `AuditResult` lives in `app/db/models.py`; `AuditAction` lives in `app/security/audit.py`.
