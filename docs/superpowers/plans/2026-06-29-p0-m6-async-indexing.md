# P0-M6 Async Indexing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move document vectorization (chunk + embed) out of the synchronous API request path into background tasks with status polling.

**Architecture:** Add a generic `TaskService` + `IngestionTask` model to track background job state. `IngestionService` stops at "create Document" and returns `(FileUpload, Document)`. API layer creates a task, submits `process_document` as a `BackgroundTask`, and returns `task_id` for client polling.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy, pytest, Alembic. No new dependencies — uses FastAPI built-in `BackgroundTasks`.

## Global Constraints

- Target Python: 3.12
- Target FastAPI: latest stable
- All code must pass `ruff check` and `ruff format`
- All new code must have tests
- Follow existing file naming and import style (`app.db.models`, `app.services.ingestion.*`)
- Use `Annotated[Session, Depends(get_db)]` pattern for DB injection
- Use `Annotated[AuthenticatedRequestContext, Depends(require_permission(...))]` for auth
- All API routes under `/api/v1` prefix
- UUID PKs use `CHAR(36)` with `default=lambda: str(uuid.uuid4())`
- Alembic migration filenames use `YYYYMMDD_HHMM_<description>.py`
- Tests use `pytest` with `MagicMock`/`AsyncMock` for unit, `TestClient` for integration

---

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `app/db/models.py` | Modify | Add `TaskType`, `TaskStatus`, `IngestionTask` model |
| `app/services/ingestion/tasks.py` | Create | `TaskService` — generic task CRUD + state transitions |
| `app/services/ingestion/service.py` | Modify | Remove `processor` from `IngestionService`; `ingest_file()` returns `(FileUpload, Document)` |
| `app/api/routes.py` | Modify | Add `BackgroundTasks` to upload/process; add task query endpoints; wire `_run_index_task` |
| `alembic/versions/20260629_0005_ingestion_tasks.py` | Create | Alembic migration for `ingestion_tasks` table |
| `tests/services/ingestion/test_tasks.py` | Create | `TaskService` unit tests |
| `tests/services/ingestion/test_service.py` | Modify | Update tests for new `ingest_file()` signature (no processor) |
| `tests/api/test_file_upload.py` | Modify | Update upload test to assert `task_id` in response |
| `tests/api/test_tasks.py` | Create | Task API integration tests |

---

### Task 1: Add IngestionTask model and enums

**Files:**
- Modify: `app/db/models.py`
- Test: `tests/db/test_models.py` (add model existence assertions)

**Interfaces:**
- Produces: `TaskType` enum, `TaskStatus` enum, `IngestionTask` SQLAlchemy model

- [ ] **Step 1: Write the failing test**

In `tests/db/test_models.py`, add assertions that the new enums and model exist:

```python
def test_task_type_enum_exists():
    from app.db.models import TaskType
    assert TaskType.DOCUMENT_INDEX.value == "document_index"


def test_task_status_enum_exists():
    from app.db.models import TaskStatus
    assert TaskStatus.PENDING.value == "pending"
    assert TaskStatus.RUNNING.value == "running"
    assert TaskStatus.COMPLETED.value == "completed"
    assert TaskStatus.FAILED.value == "failed"
    assert TaskStatus.CANCELLED.value == "cancelled"


def test_ingestion_task_model_exists():
    from app.db.models import IngestionTask
    assert IngestionTask.__tablename__ == "ingestion_tasks"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Users/sma2lbao/Code/beauty-moon/apps/luna-corpus
pytest tests/db/test_models.py::test_task_type_enum_exists -v
pytest tests/db/test_models.py::test_task_status_enum_exists -v
pytest tests/db/test_models.py::test_ingestion_task_model_exists -v
```

Expected: `ImportError: cannot import name 'TaskType' from 'app.db.models'`

- [ ] **Step 3: Write minimal implementation**

In `app/db/models.py`, after the `Message` class, add:

```python
class TaskType(str, enum.Enum):
    """Type of background ingestion task."""

    DOCUMENT_INDEX = "document_index"


class TaskStatus(str, enum.Enum):
    """Status of a background ingestion task."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class IngestionTask(Base):
    """Background ingestion task tracking."""

    __tablename__ = "ingestion_tasks"

    id: Mapped[str] = mapped_column(
        CHAR(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    type: Mapped[TaskType] = mapped_column(Enum(TaskType), nullable=False)
    status: Mapped[TaskStatus] = mapped_column(
        Enum(TaskStatus), default=TaskStatus.PENDING, nullable=False
    )
    target_id: Mapped[str] = mapped_column(String(36), nullable=False)
    knowledge_base_id: Mapped[str] = mapped_column(
        CHAR(36), ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/db/test_models.py::test_task_type_enum_exists -v
pytest tests/db/test_models.py::test_task_status_enum_exists -v
pytest tests/db/test_models.py::test_ingestion_task_model_exists -v
```

Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add app/db/models.py tests/db/test_models.py
git commit -m "feat(db): add TaskType, TaskStatus, IngestionTask model"
```

---

### Task 2: Create TaskService with state machine

**Files:**
- Create: `app/services/ingestion/tasks.py`
- Test: `tests/services/ingestion/test_tasks.py`

**Interfaces:**
- Consumes: `TaskType`, `TaskStatus`, `IngestionTask` from `app.db.models`
- Produces: `TaskService` class with methods used by later tasks:
  - `create_task(db, type, target_id, kb_id) -> IngestionTask`
  - `get_task(db, task_id) -> IngestionTask | None`
  - `get_task_by_target(db, type, target_id) -> IngestionTask | None`
  - `list_tasks(db, kb_id, status=None, limit=50) -> list[IngestionTask]`
  - `mark_running(db, task_id) -> IngestionTask`
  - `mark_completed(db, task_id) -> IngestionTask`
  - `mark_failed(db, task_id, error_message) -> IngestionTask`

- [ ] **Step 1: Write the failing test**

Create `tests/services/ingestion/test_tasks.py`:

```python
"""Tests for TaskService."""
from datetime import datetime
from unittest.mock import MagicMock

import pytest

from app.db.models import IngestionTask, TaskStatus, TaskType
from app.services.ingestion.tasks import TaskService


@pytest.fixture
def task_service():
    return TaskService()


def test_create_task(task_service):
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = None

    task = task_service.create_task(
        db, TaskType.DOCUMENT_INDEX, "doc-1", "kb-1"
    )

    assert task.type == TaskType.DOCUMENT_INDEX
    assert task.status == TaskStatus.PENDING
    assert task.target_id == "doc-1"
    assert task.knowledge_base_id == "kb-1"
    db.add.assert_called_once()
    db.commit.assert_called()


def test_create_task_deduplication(task_service):
    db = MagicMock()
    existing = MagicMock()
    existing.status = TaskStatus.PENDING
    db.query.return_value.filter.return_value.first.return_value = existing

    task = task_service.create_task(
        db, TaskType.DOCUMENT_INDEX, "doc-1", "kb-1"
    )

    assert task is existing
    db.add.assert_not_called()


def test_get_task(task_service):
    db = MagicMock()
    expected = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = expected

    result = task_service.get_task(db, "task-1")

    assert result is expected


def test_list_tasks(task_service):
    db = MagicMock()
    task1 = MagicMock()
    task2 = MagicMock()
    db.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = [task1, task2]

    results = task_service.list_tasks(db, "kb-1")

    assert len(results) == 2


def test_list_tasks_with_status_filter(task_service):
    db = MagicMock()
    db.query.return_value.filter.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = []

    results = task_service.list_tasks(db, "kb-1", status=TaskStatus.COMPLETED)

    assert results == []


def test_mark_running(task_service):
    db = MagicMock()
    task = MagicMock()
    task.status = TaskStatus.PENDING
    db.query.return_value.filter.return_value.first.return_value = task

    result = task_service.mark_running(db, "task-1")

    assert result.status == TaskStatus.RUNNING
    assert result.started_at is not None
    db.commit.assert_called()


def test_mark_completed(task_service):
    db = MagicMock()
    task = MagicMock()
    task.status = TaskStatus.RUNNING
    db.query.return_value.filter.return_value.first.return_value = task

    result = task_service.mark_completed(db, "task-1")

    assert result.status == TaskStatus.COMPLETED
    assert result.completed_at is not None
    db.commit.assert_called()


def test_mark_failed(task_service):
    db = MagicMock()
    task = MagicMock()
    task.status = TaskStatus.RUNNING
    db.query.return_value.filter.return_value.first.return_value = task

    result = task_service.mark_failed(db, "task-1", "Something broke")

    assert result.status == TaskStatus.FAILED
    assert result.error_message == "Something broke"
    assert result.completed_at is not None
    db.commit.assert_called()
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/services/ingestion/test_tasks.py -v
```

Expected: `ModuleNotFoundError: No module named 'app.services.ingestion.tasks'`

- [ ] **Step 3: Write minimal implementation**

Create `app/services/ingestion/tasks.py`:

```python
"""Task service for managing background ingestion tasks."""
from datetime import datetime

from sqlalchemy.orm import Session

from app.db.models import IngestionTask, TaskStatus, TaskType


class TaskService:
    """Manage ingestion task lifecycle."""

    def create_task(
        self,
        db: Session,
        type: TaskType,
        target_id: str,
        knowledge_base_id: str,
    ) -> IngestionTask:
        """Create a new task, or return existing pending/running task for same target."""
        existing = self.get_task_by_target(db, type, target_id)
        if existing and existing.status in (TaskStatus.PENDING, TaskStatus.RUNNING):
            return existing

        task = IngestionTask(
            type=type,
            target_id=target_id,
            knowledge_base_id=knowledge_base_id,
            status=TaskStatus.PENDING,
        )
        db.add(task)
        db.commit()
        db.refresh(task)
        return task

    def get_task(self, db: Session, task_id: str) -> IngestionTask | None:
        """Get task by ID."""
        return db.query(IngestionTask).filter(IngestionTask.id == task_id).first()

    def get_task_by_target(
        self, db: Session, type: TaskType, target_id: str
    ) -> IngestionTask | None:
        """Get most recent task for a given type + target."""
        return (
            db.query(IngestionTask)
            .filter(IngestionTask.type == type, IngestionTask.target_id == target_id)
            .order_by(IngestionTask.created_at.desc())
            .first()
        )

    def list_tasks(
        self,
        db: Session,
        knowledge_base_id: str,
        status: TaskStatus | None = None,
        limit: int = 50,
    ) -> list[IngestionTask]:
        """List tasks for a knowledge base, optionally filtered by status."""
        query = db.query(IngestionTask).filter(
            IngestionTask.knowledge_base_id == knowledge_base_id
        )
        if status:
            query = query.filter(IngestionTask.status == status)
        return query.order_by(IngestionTask.created_at.desc()).limit(limit).all()

    def mark_running(self, db: Session, task_id: str) -> IngestionTask:
        """Mark task as running and set started_at."""
        task = self.get_task(db, task_id)
        if task:
            task.status = TaskStatus.RUNNING
            task.started_at = datetime.now()
            db.commit()
            db.refresh(task)
        return task

    def mark_completed(self, db: Session, task_id: str) -> IngestionTask:
        """Mark task as completed and set completed_at."""
        task = self.get_task(db, task_id)
        if task:
            task.status = TaskStatus.COMPLETED
            task.completed_at = datetime.now()
            db.commit()
            db.refresh(task)
        return task

    def mark_failed(
        self, db: Session, task_id: str, error_message: str
    ) -> IngestionTask:
        """Mark task as failed, record error, and set completed_at."""
        task = self.get_task(db, task_id)
        if task:
            task.status = TaskStatus.FAILED
            task.error_message = error_message
            task.completed_at = datetime.now()
            db.commit()
            db.refresh(task)
        return task
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/services/ingestion/test_tasks.py -v
```

Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add app/services/ingestion/tasks.py tests/services/ingestion/test_tasks.py
git commit -m "feat(tasks): add TaskService with state machine and deduplication"
```

---

### Task 3: Remove processor from IngestionService, make ingest_file return (FileUpload, Document)

**Files:**
- Modify: `app/services/ingestion/service.py`
- Test: `tests/services/ingestion/test_service.py` (update existing tests)

**Interfaces:**
- Consumes: `TaskService` from Task 2 (not directly — `IngestionService` stays unaware of tasks)
- Produces: `IngestionService.__init__` no longer takes `processor`; `ingest_file()` returns `(FileUpload, Document)` tuple instead of `FileUpload`

- [ ] **Step 1: Write the failing test (update existing)**

In `tests/services/ingestion/test_service.py`, update tests to reflect new signature:

First, update the fixture to not pass `processor`:

```python
@pytest.fixture
def ingestion_service(mock_storage, mock_parser_registry):
    """Create ingestion service with mocked dependencies."""
    return IngestionService(
        storage=mock_storage,
        parser_registry=mock_parser_registry,
        max_upload_size=52428800,
        duplicate_policy="reject",
    )
```

Remove `mock_processor` fixture and update `ingest_file_success` test:

```python
@pytest.mark.asyncio
async def test_ingest_file_success(ingestion_service, mock_storage):
    """Test successful file ingestion returns FileUpload and Document."""
    db = MagicMock()
    file = _mock_upload_file("test.pdf", "application/pdf", 1024, b"pdf content")

    # Mock hash check - no duplicate
    db.query.return_value.filter.return_value.first.return_value = None

    upload, document = await ingestion_service.ingest_file(db, file, "kb-1")

    assert isinstance(upload, FileUpload)
    assert upload.status == FileUploadStatus.UPLOADED
    mock_storage.save.assert_called_once()
    db.add.assert_called()
    db.commit.assert_called()
    # Document was created but NOT processed
    assert document is not None
```

Update `test_ingest_file_generic_exception_rollback` — since `processor` is no longer called inside `ingest_file`, the test should be removed or rewritten. The new behavior: `ingest_file` only throws on parse/storage errors, not on vectorization (which happens outside now). Remove this test.

Update `test_delete_file` — fixture no longer has processor, but `delete_file` doesn't need it anyway. The test should still pass.

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/services/ingestion/test_service.py -v
```

Expected: FAIL — `IngestionService.__init__` still expects `processor` param, or `ingest_file` returns single `FileUpload` not tuple.

- [ ] **Step 3: Write minimal implementation**

In `app/services/ingestion/service.py`:

1. Remove `processor` from `__init__`:

```python
class IngestionService:
    """Orchestrate file upload -> storage -> parse -> document creation."""

    def __init__(
        self,
        storage: StorageBackend,
        parser_registry: ParserRegistry,
        max_upload_size: int = 52428800,
        duplicate_policy: str = "reject",
    ):
        self.storage = storage
        self.parser_registry = parser_registry
        self.max_upload_size = max_upload_size
        self.duplicate_policy = duplicate_policy
```

2. Change `ingest_file` return type annotation and body:

```python
    async def ingest_file(
        self,
        db: Session,
        file: UploadFile,
        knowledge_base_id: str,
    ) -> tuple[FileUpload, Document]:
        """Ingest a file: store, parse, create document. Returns (FileUpload, Document).

        Document processing (chunk + vectorize) is the caller's responsibility.
        """
```

3. In the success path, after creating Document, remove the `process_document` call and the FileUpload status update to `PARSED`. Instead:
   - Document status stays `PENDING` (it was never set to PROCESSING because process_document wasn't called)
   - FileUpload status stays `UPLOADED`
   - Return `(upload, document)`

4. In the exception handler (the broad `except Exception` block), remove the `processor.process_document` rollback logic. Since `process_document` is no longer called here, the only possible failures are parse/storage/DB errors. The existing rollback logic for Document deletion on failure should remain (it catches any failure after Document creation).

The key changes inside `ingest_file`:

```python
        try:
            # Save to storage
            await self.storage.save(file, stored_name)

            # Parse content
            parser = self.parser_registry.get_parser(mime_type)
            parsed_text = parser.parse(content, filename)

            # Create Document
            document = Document(
                knowledge_base_id=knowledge_base_id,
                file_id=upload.id,
                title=filename or "Untitled",
                content=parsed_text,
                source=f"file://{filename}",
                has_tables="|" in parsed_text and "---" in parsed_text,
                has_code="```" in parsed_text or "def " in parsed_text,
                status=ContentStatus.PENDING,
            )
            db.add(document)
            db.commit()
            db.refresh(document)

            return upload, document

        except ParseError as e:
            upload.status = FileUploadStatus.ERROR
            upload.error_message = str(e)
            db.commit()
            with contextlib.suppress(StorageError):
                await self.storage.delete(stored_name)
            return upload, None

        except Exception as e:
            upload.status = FileUploadStatus.ERROR
            upload.error_message = str(e)
            db.commit()
            # Rollback: delete document if created
            doc = (
                db.query(Document)
                .filter(
                    Document.file_id == upload.id,
                    Document.knowledge_base_id == knowledge_base_id,
                )
                .first()
            )
            if doc:
                db.delete(doc)
                db.commit()
            with contextlib.suppress(StorageError):
                await self.storage.delete(stored_name)
            return upload, None
```

Note: Return type is `tuple[FileUpload, Document | None]`.

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/services/ingestion/test_service.py -v
```

Expected: All PASS (after updating tests for new signature)

- [ ] **Step 5: Commit**

```bash
git add app/services/ingestion/service.py tests/services/ingestion/test_service.py
git commit -m "refactor(ingestion): remove processor from IngestionService, return (FileUpload, Document)"
```

---

### Task 4: Add _run_index_task background function and wire into API

**Files:**
- Modify: `app/api/routes.py`
- Test: `tests/api/test_file_upload.py` (update)

**Interfaces:**
- Consumes: `TaskService` from Task 2, `IngestionService` from Task 3
- Produces: `_run_index_task(task_id: str, document_id: str) -> None` function; modified `upload_file` and `process_document` endpoints

- [ ] **Step 1: Write the failing test (update existing upload test)**

In `tests/api/test_file_upload.py`, update `test_upload_file_success` to assert `task_id` in response:

```python
@patch("app.api.routes.get_storage_backend")
@patch("app.api.routes.get_parser_registry")
def test_upload_file_success(mock_registry, mock_storage, client, app_db):
    """Test successful file upload returns task_id."""
    _, Session, context = app_db
    user_id = create_user_with_permissions(
        Session,
        context["workspace_id"],
        "file_uploader",
        [PermissionSlug.DOCUMENT_WRITE],
    )

    storage = mock_storage.return_value
    async def mock_save(f, p):
        return p
    storage.save = mock_save

    registry = mock_registry.return_value
    registry.is_supported.return_value = True
    parser = type("Parser", (), {"parse": lambda self, c, n: "Parsed text"})()
    registry.get_parser.return_value = parser

    response = client.post(
        "/api/v1/files/upload",
        headers=_auth_headers(context, context["kb_one_id"], user_id),
        files={"file": ("test.txt", io.BytesIO(b"Hello"), "text/plain")},
    )

    assert response.status_code == 201
    data = response.json()
    assert data["file"]["original_name"] == "test.txt"
    assert data["file"]["mime_type"] == "text/plain"
    assert "task_id" in data
    assert data["document_id"] is not None
```

Note: Remove the `mock_processor` patch since `DocumentProcessor` is no longer instantiated in the upload handler.

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/api/test_file_upload.py::test_upload_file_success -v
```

Expected: FAIL — `task_id` not in response, or `DocumentProcessor` patch still expected.

- [ ] **Step 3: Write minimal implementation**

In `app/api/routes.py`:

1. Add new imports at the top:

```python
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, UploadFile, status
```

2. Add new response models:

```python
class TaskResponse(BaseModel):
    """Task response model."""

    id: str
    type: str
    status: str
    target_id: str
    error_message: str | None
    started_at: str | None
    completed_at: str | None
    created_at: str
    updated_at: str

    model_config = ConfigDict(from_attributes=True)


class TaskListResponse(BaseModel):
    """Task list response."""

    tasks: list[TaskResponse]
    total: int
```

3. Update `FileUploadCreateResponse` to include `task_id`:

```python
class FileUploadCreateResponse(BaseModel):
    """File upload creation response with document and task info."""

    file: FileUploadResponse
    document_id: str | None
    task_id: str | None
```

4. Add the background task function (at module level, before routes or after imports):

```python
from app.db.database import SessionLocal
from app.services.ingestion.tasks import TaskService


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
    except Exception as e:
        task_service = TaskService()
        task_service.mark_failed(db, task_id, error_message=str(e))
    finally:
        db.close()
```

5. Update `upload_file` endpoint:

```python
@router.post(
    "/files/upload",
    response_model=FileUploadCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_file(
    file: UploadFile,
    background_tasks: BackgroundTasks,
    db: Annotated[Session, Depends(get_db)],
    context: Annotated[
        AuthenticatedRequestContext,
        Depends(require_permission(PermissionSlug.DOCUMENT_WRITE)),
    ],
) -> FileUploadCreateResponse:
    """Upload a file, parse it, create a document, and queue for indexing."""
    storage = get_storage_backend()
    registry = get_parser_registry()

    service = IngestionService(
        storage=storage,
        parser_registry=registry,
        max_upload_size=get_settings().max_upload_size,
        duplicate_policy=get_settings().upload_duplicate_policy,
    )

    try:
        upload, document = await service.ingest_file(db, file, context.knowledge_base.id)
    except UnsupportedFileTypeError as e:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=str(e),
        ) from e
    except DuplicateFileError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e),
        ) from e
    except Exception as e:
        if isinstance(e, HTTPException):
            raise
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        ) from e

    # Create indexing task and submit to background
    task_service = TaskService()
    task = task_service.create_task(
        db, TaskType.DOCUMENT_INDEX, document.id, context.knowledge_base.id
    )
    background_tasks.add_task(_run_index_task, task.id, document.id)

    return FileUploadCreateResponse(
        file=FileUploadResponse(
            id=upload.id,
            knowledge_base_id=upload.knowledge_base_id,
            original_name=upload.original_name,
            mime_type=upload.mime_type,
            size_bytes=upload.size_bytes,
            content_hash=upload.content_hash,
            status=upload.status.value,
            error_message=upload.error_message,
            parsed_at=upload.parsed_at.isoformat() if upload.parsed_at else None,
            created_at=upload.created_at.isoformat(),
            updated_at=upload.updated_at.isoformat(),
        ),
        document_id=document.id,
        task_id=task.id,
    )
```

6. Update `process_document` endpoint to be async:

```python
@router.post("/documents/{document_id}/process")
async def process_document(
    document_id: str,
    background_tasks: BackgroundTasks,
    db: Annotated[Session, Depends(get_db)],
    context: Annotated[
        AuthenticatedRequestContext,
        Depends(require_permission(PermissionSlug.DOCUMENT_WRITE)),
    ],
) -> dict[str, str]:
    """Queue a document for processing (chunk + vectorize)."""
    doc = (
        db.query(Document)
        .filter(
            Document.id == document_id,
            Document.knowledge_base_id == context.knowledge_base.id,
        )
        .first()
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    task_service = TaskService()
    task = task_service.create_task(
        db, TaskType.DOCUMENT_INDEX, doc.id, context.knowledge_base.id
    )
    background_tasks.add_task(_run_index_task, task.id, doc.id)

    return {"task_id": task.id, "status": task.status.value}
```

7. Remove `ProcessResponse` model (no longer used by `process_document`). If other code uses it, keep it; if only this endpoint used it, it can be removed. Check: `ProcessResponse` is only used by `/documents/{id}/process`. Since we changed that endpoint to return `dict`, `ProcessResponse` is unused. But to be safe, leave it in place — removing it is a separate cleanup.

Actually, to keep the plan focused: leave `ProcessResponse` in place. It can be cleaned up later.

8. Update `delete_file` endpoint — it no longer needs `processor`:

```python
    storage = get_storage_backend()
    registry = get_parser_registry()

    service = IngestionService(
        storage=storage,
        parser_registry=registry,
    )
```

9. Add task query endpoints:

```python
@router.get("/tasks", response_model=TaskListResponse)
async def list_tasks(
    db: Annotated[Session, Depends(get_db)],
    context: Annotated[
        AuthenticatedRequestContext,
        Depends(require_permission(PermissionSlug.DOCUMENT_READ)),
    ],
    status_filter: TaskStatus | None = None,
    limit: int = Query(default=50, ge=1, le=100),
) -> TaskListResponse:
    """List ingestion tasks for the knowledge base."""
    task_service = TaskService()
    tasks = task_service.list_tasks(
        db, context.knowledge_base.id, status=status_filter, limit=limit
    )

    return TaskListResponse(
        tasks=[
            TaskResponse(
                id=t.id,
                type=t.type.value,
                status=t.status.value,
                target_id=t.target_id,
                error_message=t.error_message,
                started_at=t.started_at.isoformat() if t.started_at else None,
                completed_at=t.completed_at.isoformat() if t.completed_at else None,
                created_at=t.created_at.isoformat(),
                updated_at=t.updated_at.isoformat(),
            )
            for t in tasks
        ],
        total=len(tasks),
    )


@router.get("/tasks/{task_id}", response_model=TaskResponse)
async def get_task(
    task_id: str,
    db: Annotated[Session, Depends(get_db)],
    context: Annotated[
        AuthenticatedRequestContext,
        Depends(require_permission(PermissionSlug.DOCUMENT_READ)),
    ],
) -> TaskResponse:
    """Get a task by ID."""
    task_service = TaskService()
    task = task_service.get_task(db, task_id)

    if not task or task.knowledge_base_id != context.knowledge_base.id:
        raise HTTPException(status_code=404, detail="Task not found")

    return TaskResponse(
        id=task.id,
        type=task.type.value,
        status=task.status.value,
        target_id=task.target_id,
        error_message=task.error_message,
        started_at=task.started_at.isoformat() if task.started_at else None,
        completed_at=task.completed_at.isoformat() if task.completed_at else None,
        created_at=task.created_at.isoformat(),
        updated_at=task.updated_at.isoformat(),
    )
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/api/test_file_upload.py::test_upload_file_success -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/api/routes.py tests/api/test_file_upload.py
git commit -m "feat(api): async document indexing with BackgroundTasks and task endpoints"
```

---

### Task 5: Create Alembic migration for ingestion_tasks table

**Files:**
- Create: `alembic/versions/20260629_0005_ingestion_tasks.py`

**Interfaces:**
- Consumes: `IngestionTask` model from Task 1
- Produces: Alembic migration that creates `ingestion_tasks` table

- [ ] **Step 1: Generate migration file**

```bash
cd /Users/sma2lbao/Code/beauty-moon/apps/luna-corpus
alembic revision --autogenerate -m "add ingestion_tasks table"
```

- [ ] **Step 2: Verify migration content**

Read the generated file at `alembic/versions/20260629_0005_ingestion_tasks.py` (or similar timestamp). It should contain:

```python
"""add ingestion_tasks table

Revision ID: 20260629_0005
Revises: 20260625_0004
Create Date: 2026-06-29
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "20260629_0005"
down_revision: str | None = "20260625_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ingestion_tasks",
        sa.Column("id", mysql.CHAR(36), nullable=False),
        sa.Column("type", sa.Enum("document_index", name="tasktype"), nullable=False),
        sa.Column(
            "status",
            sa.Enum("pending", "running", "completed", "failed", "cancelled", name="taskstatus"),
            nullable=False,
        ),
        sa.Column("target_id", sa.String(36), nullable=False),
        sa.Column("knowledge_base_id", mysql.CHAR(36), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("NOW()")),
        sa.ForeignKeyConstraint(
            ["knowledge_base_id"], ["knowledge_bases.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("ingestion_tasks")
    op.execute("DROP TYPE IF EXISTS tasktype")
    op.execute("DROP TYPE IF EXISTS taskstatus")
```

If the autogenerated migration differs (e.g., uses `sa.String(36)` instead of `mysql.CHAR(36)` for `id`), adjust to match existing migration style. The `id` column should be `mysql.CHAR(36)` to match other models.

- [ ] **Step 3: Test migration**

```bash
alembic upgrade head
alembic downgrade -1
alembic upgrade head
```

Expected: All commands succeed without errors.

- [ ] **Step 4: Commit**

```bash
git add alembic/versions/20260629_0005_ingestion_tasks.py
git commit -m "feat(db): add alembic migration for ingestion_tasks table"
```

---

### Task 6: Add task API integration tests

**Files:**
- Create: `tests/api/test_tasks.py`

**Interfaces:**
- Consumes: Task endpoints from Task 4

- [ ] **Step 1: Write the failing test**

Create `tests/api/test_tasks.py`:

```python
"""Integration tests for task endpoints."""
from app.auth.permissions import PermissionSlug
from app.db.models import IngestionTask, TaskStatus, TaskType
from tests.api.test_file_upload import (
    _auth_headers,
    create_user_with_permissions,
)


def test_list_tasks_requires_auth(client):
    """Test list tasks requires authentication."""
    response = client.get("/api/v1/tasks")
    assert response.status_code == 400


def test_get_task_requires_auth(client):
    """Test get task requires authentication."""
    response = client.get("/api/v1/tasks/task-1")
    assert response.status_code == 400


def test_list_tasks_empty(client, app_db):
    """Test listing tasks with no tasks returns empty list."""
    _, Session, context = app_db
    user_id = create_user_with_permissions(
        Session,
        context["workspace_id"],
        "task_reader",
        [PermissionSlug.DOCUMENT_READ],
    )

    response = client.get(
        "/api/v1/tasks",
        headers=_auth_headers(context, context["kb_one_id"], user_id),
    )

    assert response.status_code == 200
    data = response.json()
    assert data["tasks"] == []
    assert data["total"] == 0


def test_list_tasks_with_filter(client, app_db):
    """Test listing tasks with status filter."""
    _, Session, context = app_db
    user_id = create_user_with_permissions(
        Session,
        context["workspace_id"],
        "task_reader",
        [PermissionSlug.DOCUMENT_READ],
    )

    # Create a task directly
    session = Session()
    task = IngestionTask(
        type=TaskType.DOCUMENT_INDEX,
        status=TaskStatus.COMPLETED,
        target_id="doc-1",
        knowledge_base_id=context["kb_one_id"],
    )
    session.add(task)
    session.commit()
    session.close()

    response = client.get(
        "/api/v1/tasks?status=completed",
        headers=_auth_headers(context, context["kb_one_id"], user_id),
    )

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert data["tasks"][0]["status"] == "completed"


def test_get_task_not_found(client, app_db):
    """Test getting a non-existent task."""
    _, Session, context = app_db
    user_id = create_user_with_permissions(
        Session,
        context["workspace_id"],
        "task_reader",
        [PermissionSlug.DOCUMENT_READ],
    )

    response = client.get(
        "/api/v1/tasks/nonexistent",
        headers=_auth_headers(context, context["kb_one_id"], user_id),
    )

    assert response.status_code == 404


def test_get_task_cross_kb_404(client, app_db):
    """Test getting a task from different knowledge base returns 404."""
    _, Session, context = app_db

    # Create another KB
    from app.db.models import KnowledgeBase, Workspace

    session = Session()
    workspace = session.query(Workspace).filter(Workspace.id == context["workspace_id"]).first()
    kb_two = KnowledgeBase(name="Other", slug="other", workspace=workspace)
    session.add(kb_two)

    task = IngestionTask(
        type=TaskType.DOCUMENT_INDEX,
        status=TaskStatus.PENDING,
        target_id="doc-1",
        knowledge_base_id=kb_two.id,
    )
    session.add(task)
    session.commit()
    task_id = task.id
    session.close()

    user_id = create_user_with_permissions(
        Session,
        context["workspace_id"],
        "task_reader",
        [PermissionSlug.DOCUMENT_READ],
    )

    response = client.get(
        f"/api/v1/tasks/{task_id}",
        headers=_auth_headers(context, context["kb_one_id"], user_id),
    )

    assert response.status_code == 404
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/api/test_tasks.py -v
```

Expected: Some may fail if routes not fully wired; at minimum `test_list_tasks_requires_auth` and `test_get_task_requires_auth` should pass (they test 400 from missing auth headers).

- [ ] **Step 3: Run full test to verify all passes**

```bash
pytest tests/api/test_tasks.py -v
```

Expected: All PASS

- [ ] **Step 4: Commit**

```bash
git add tests/api/test_tasks.py
git commit -m "test(api): add task endpoint integration tests"
```

---

### Task 7: Run full test suite and fix any regressions

**Files:**
- All modified files (potential ruff/lint fixes)

- [ ] **Step 1: Run ruff check**

```bash
cd /Users/sma2lbao/Code/beauty-moon/apps/luna-corpus
ruff check app/ tests/
```

Expected: Clean (no errors)

- [ ] **Step 2: Run ruff format**

```bash
ruff format app/ tests/
```

- [ ] **Step 3: Run full test suite**

```bash
pytest tests/ -v --tb=short
```

Expected: All tests pass. If any fail:

- `test_service.py` failures: Likely `ingest_file` return value assertions still expecting single FileUpload
- `test_file_upload.py` failures: Likely `mock_processor` patch still present, or `task_id` assertion missing
- `test_tasks.py` failures: Check Task endpoint routing or model import issues

- [ ] **Step 4: Fix any issues and re-run**

Iterate until clean.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "style: ruff format and fix lint violations"
```

---

## Self-Review

### 1. Spec coverage check

| Spec requirement | Task |
|---|---|
| TaskType / TaskStatus enums | Task 1 |
| IngestionTask model | Task 1 |
| TaskService with state machine | Task 2 |
| IngestionService remove processor | Task 3 |
| ingest_file returns (FileUpload, Document) | Task 3 |
| _run_index_task background function | Task 4 |
| POST /files/upload returns task_id | Task 4 |
| POST /documents/{id}/process async | Task 4 |
| GET /tasks, GET /tasks/{id} | Task 4 |
| Alembic migration | Task 5 |
| TaskService unit tests | Task 2 |
| Upload test updated for async | Task 4 |
| Task API integration tests | Task 6 |
| Full suite pass + ruff clean | Task 7 |

**Gap:** None identified.

### 2. Placeholder scan

- No "TBD", "TODO", "implement later" found
- No vague "add error handling" without specifics
- All test code includes actual assertions
- All steps include exact file paths and commands

### 3. Type consistency check

- `ingest_file()` returns `tuple[FileUpload, Document | None]` — consistent across service (Task 3) and API (Task 4)
- `TaskService` methods use `Session` type consistently
- `TaskStatus`/`TaskType` enums used consistently in models, service, API
- `FileUploadCreateResponse` adds `task_id: str | None` — consistent with optional return

**All clear.**
