# P0-M6 异步索引任务设计

## 目标

将文档向量化（chunk + embedding）从同步 API 请求链路中拆出，改为异步执行 + 状态轮询，解决大文件、云 embedding API 调用阻塞请求的问题。

## 范围

- 新增通用后台任务管理模型 `IngestionTask` 和服务 `TaskService`
- `IngestionService` 改造：同步链路只做到"创建 Document"，不再调用 `process_document()`
- `POST /files/upload` 返回 `task_id`，客户端可轮询任务状态
- `POST /documents/{id}/process` 从同步改为异步
- 新增 `GET /tasks` 和 `GET /tasks/{id}` 查询端点
- 后台任务使用 FastAPI `BackgroundTasks`，无新依赖

## 不做

- Redis/Celery/RQ 等持久化队列（M6 之后评估）
- WebSocket 推送
- 任务取消（CANCELLED 状态预留，不实现逻辑）
- 任务重试（FAILED 后需客户端手动重新触发）
- 进程重启后的任务恢复（仅预留启动扫描思路）
- 批量任务（BATCH_IMPORT 等预留 type）

## 依赖

- P0-M2 租户/知识库模型（任务归属知识库）
- P0-M3 RBAC（任务查询需鉴权）
- P0-M5 文件摄取管线（IngestionService 是改造对象）

## 架构

```
┌─────────────────────────────────────────────────────────────┐
│  API Layer                                                  │
│  POST /files/upload  ────┐                                  │
│  GET  /tasks/{id}      ◄─┘ 返回 task_id                     │
│  POST /documents/{id}/process                               │
└──────────────────────────┬──────────────────────────────────┘
                           │
          ┌────────────────┼────────────────┐
          ▼                ▼                ▼
┌──────────────┐ ┌──────────────┐ ┌──────────────┐
│IngestionSvc  │ │ TaskService  │ │ Background   │
│(同步)        │ │              │ │ Tasks        │
│校验→存储→解析 │ │ create_task  │ │ process_doc  │
│→创建Document │ │ update_status│ │ (异步embedding)│
└──────────────┘ └──────────────┘ └──────────────┘
```

**核心分层**：

- `IngestionService.ingest_file()`：同步链路，返回 `(FileUpload, Document)`，不再碰向量化
- `TaskService`：通用后台任务管理，创建/查询/更新任务
- API 层：调用 `ingest_file()` → 创建 Task → `background_tasks.add_task()` 启动异步向量化
- `_run_index_task(task_id, document_id)`：后台函数，包装现有 `DocumentProcessor.process_document()`，捕获异常更新 Task 状态

## 数据模型

### 新增枚举

```python
class TaskType(str, enum.Enum):
    DOCUMENT_INDEX = "document_index"
    # 预留: BATCH_IMPORT, REINDEX, etc.

class TaskStatus(str, enum.Enum):
    PENDING = "pending"      # 已创建，等待执行
    RUNNING = "running"      # 正在执行
    COMPLETED = "completed"  # 成功
    FAILED = "failed"        # 失败
    CANCELLED = "cancelled"  # 已取消（预留，M6 不实现逻辑）
```

### 新增 `IngestionTask` 模型

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | CHAR(36) PK | UUID |
| `type` | Enum(TaskType) | 任务类型，M6 只有 `document_index` |
| `status` | Enum(TaskStatus) | 默认 `pending` |
| `target_id` | String(36) | 被操作对象 ID，当前为 `document_id` |
| `knowledge_base_id` | CHAR(36) FK → KnowledgeBase | 归属知识库，级联删除 |
| `error_message` | Text nullable | 失败原因 |
| `started_at` | DateTime nullable | 开始执行时间 |
| `completed_at` | DateTime nullable | 完成时间 |
| `created_at` | DateTime | server_default=func.now() |
| `updated_at` | DateTime | server_default=func.now(), onupdate=func.now() |

**约束**：无数据库级唯一约束（避免 completed 任务阻止重新索引）。防重复在应用层 `TaskService.create_task()` 中实现：查询现有 `pending`/`running` 任务，存在则返回。

**关系**：暂不建立 ORM relationship（减少模型耦合）。通过 `knowledge_base_id` 做权限过滤即可。

## 服务层

### `TaskService`

```python
class TaskService:
    def create_task(self, db, type, target_id, kb_id) -> IngestionTask
    def get_task(self, db, task_id) -> IngestionTask | None
    def get_task_by_target(self, db, type, target_id) -> IngestionTask | None
    def list_tasks(self, db, kb_id, status=None, limit=50) -> list[IngestionTask]
    def update_status(self, db, task_id, status, error_message=None) -> IngestionTask
    def mark_running(self, db, task_id) -> IngestionTask
    def mark_completed(self, db, task_id) -> IngestionTask
    def mark_failed(self, db, task_id, error_message) -> IngestionTask
```

**防重复逻辑**：

```python
def create_task(self, db, type, target_id, kb_id) -> IngestionTask:
    existing = self.get_task_by_target(db, type, target_id)
    if existing and existing.status in (TaskStatus.PENDING, TaskStatus.RUNNING):
        return existing  # 返回现有任务，不重复创建
    # 否则创建新任务
```

### `IngestionService` 改造

**构造函数移除 `processor`**：

```python
class IngestionService:
    def __init__(
        self,
        storage: StorageBackend,
        parser_registry: ParserRegistry,
        max_upload_size: int = 52428800,
        duplicate_policy: str = "reject",
    ):
```

**`ingest_file()` 新流程**：

1. 校验文件大小和 MIME type
2. 计算 content_hash，去重检测
3. 存储文件到 StorageBackend
4. 创建 `FileUpload` 记录（status = uploaded）
5. 解析文本
6. 创建 `Document`（status = pending，不调用 process_document）
7. 返回 `(FileUpload, Document)`

异常回滚：解析失败时 IngestionService 仍清理已存储文件并更新 FileUpload.status = error（M5 逻辑不变）。向量化失败不再由 IngestionService 处理，移至后台任务中捕获异常并更新 Task.status = failed + Document.status = error。

### 后台任务函数

```python
def _run_index_task(task_id: str, document_id: str) -> None:
    """Background task: chunk + embed + vectorize."""
    db = SessionLocal()
    try:
        task_service = TaskService()
        task_service.mark_running(db, task_id)

        processor = DocumentProcessor()
        processor.process_document(db, document_id)
        # process_document 内部会更新 Document.status: processing → completed/error

        task_service.mark_completed(db, task_id)
    except Exception as e:
        task_service.mark_failed(db, task_id, error_message=str(e))
        # Document.status 已被 process_document 设为 error
    finally:
        db.close()
```

**设计理由**：

- 使用独立 `SessionLocal()`，避免和 API 请求 session 冲突
- 异常全捕获，不泄漏到 FastAPI 的 background task runner
- `process_document` 内部已有 Document.status 状态机，TaskService 只维护任务层状态

## API 层

### 端点改造

| 方法 | 路径 | 改动 |
|---|---|---|
| `POST` | `/files/upload` | 新增 `BackgroundTasks` 参数；返回体新增 `task_id`；后台启动向量化 |
| `POST` | `/documents/{id}/process` | 从同步改为异步：创建 Task + background task，返回 `{task_id, status}` |

### 新增端点

| 方法 | 路径 | 说明 | 权限 |
|---|---|---|---|
| `GET` | `/tasks` | 列出知识库任务，支持 `?status=` 过滤 | `document:read` |
| `GET` | `/tasks/{task_id}` | 查询单个任务状态 | `document:read` |

### `POST /files/upload` 新流程

```python
async def upload_file(
    file: UploadFile,
    background_tasks: BackgroundTasks,
    db: Session,
    context: AuthenticatedRequestContext,
):
    # 1. 同步链路
    service = IngestionService(storage, registry)
    upload, document = await service.ingest_file(db, file, context.kb.id)

    # 2. 创建后台任务（防重复）
    task = task_service.create_task(
        db, TaskType.DOCUMENT_INDEX, document.id, context.kb.id
    )

    # 3. 提交后台任务
    background_tasks.add_task(_run_index_task, task.id, document.id)

    # 4. 返回
    return FileUploadCreateResponse(
        file=..., document_id=document.id, task_id=task.id
    )
```

### `POST /documents/{id}/process` 新流程

```python
async def process_document(
    document_id: str,
    background_tasks: BackgroundTasks,
    db: Session,
    context: AuthenticatedRequestContext,
):
    # 验证 document 存在且属于当前知识库
    doc = ...

    # 创建任务（防重复）
    task = task_service.create_task(
        db, TaskType.DOCUMENT_INDEX, doc.id, context.kb.id
    )
    background_tasks.add_task(_run_index_task, task.id, doc.id)

    return {"task_id": task.id, "status": task.status.value}
```

### 响应模型

```python
class TaskResponse(BaseModel):
    id: str
    type: str
    status: str
    target_id: str
    error_message: str | None
    started_at: str | None
    completed_at: str | None
    created_at: str
    updated_at: str

class TaskListResponse(BaseModel):
    tasks: list[TaskResponse]
    total: int
```

## 状态流转

### 三层状态各司其职

| 层级 | 状态对象 | 状态流 | 含义 |
|---|---|---|---|
| 文件层 | `FileUpload.status` | `uploaded` / `parsed` / `error` | 文件解析是否成功（M5 逻辑不变） |
| 文档层 | `Document.status` | `pending` → `processing` → `completed` / `error` | 向量化进度（process_document 维护） |
| 任务层 | `IngestionTask.status` | `pending` → `running` → `completed` / `failed` | 后台任务执行结果 |

### 成功路径

```
POST /files/upload
  → IngestionService.ingest_file() 同步执行
    → FileUpload.status = uploaded
    → Document.status = pending
  → TaskService.create_task() → status = pending
  → background_tasks.add_task(_run_index_task)
  ← API 返回 {file, document_id, task_id}

后台 _run_index_task:
  → mark_running → status = running
  → process_document() → Document.status = processing → completed
  → mark_completed → status = completed
```

### 失败路径（embedding API 超时）

```
后台 _run_index_task:
  → mark_running → status = running
  → process_document() 抛异常 → Document.status = error
  → mark_failed → status = failed, error_message = "Embedding timeout"
```

客户端通过 `GET /tasks/{task_id}` 轮询，看到 `failed` 后可查看 `error_message`。

## 错误处理

### 后台任务错误

后台任务在独立 session 中运行，API 已返回，HTTP 异常无法传达。错误通过 Task 模型承载。

| 场景 | Document.status | Task.status | error_message 示例 |
|---|---|---|---|
| 向量化正常完成 | `completed` | `completed` | `None` |
| embedding API 超时 | `error` | `failed` | `"Embedding timeout after 30s"` |
| Chroma 写入失败 | `error` | `failed` | `"Vector store write failed: ..."` |
| 重复提交（已有 pending/running 任务）| 不变 | 返回现有任务 | — |

### 防重复提交

`IngestionTask` 的 `UniqueConstraint("type", "target_id")` 保证同一目标同一类型只有一个进行中的任务。`TaskService.create_task()` 先查询现有进行中任务，存在则返回。

`POST /documents/{id}/process` 的幂等行为：

- 已有 `pending`/`running` 任务 → 返回该 task_id
- 已有 `completed` 任务 → 创建新任务（允许重新索引）
- 已有 `failed` 任务 → 创建新任务（重试）

### 进程重启丢失

`BackgroundTasks` 的任务在进程重启时丢失。M6 的缓解策略：

1. 创建 Task 记录**先于** `add_task()`，丢失后可从 `pending` 状态的任务恢复
2. 启动时（lifespan）扫描 `pending`/`running` 任务，标记为 `failed`，并记录 `"Process restarted"`（预留实现）

## 主要改动点

| 文件 | 改动 |
|---|---|
| `app/db/models.py` | 新增 `TaskType`、`TaskStatus`、`IngestionTask` |
| `app/services/ingestion/tasks.py` | 新增 `TaskService` |
| `app/services/ingestion/service.py` | `IngestionService` 移除 `processor` 参数和 `process_document()` 调用 |
| `app/api/routes.py` | 改造 `POST /files/upload`、`POST /documents/{id}/process`；新增 `GET /tasks`、`GET /tasks/{id}` |
| `alembic/versions/20260629_0005_ingestion_tasks.py` | 新增 migration |
| `tests/services/ingestion/test_tasks.py` | TaskService 单元测试 |
| `tests/api/test_file_upload.py` | 改造上传测试（验证异步流程） |
| `tests/api/test_tasks.py` | 新增任务 API 集成测试 |

## 测试策略

| 层级 | 目标 | 关键用例 |
|---|---|---|
| **单元测试** | `TaskService` 状态机 | create/get/list/update, 防重复约束, mark_running/completed/failed |
| **单元测试** | `IngestionService` 改造后 | ingest_file 不调用 process_document, 正确返回 (FileUpload, Document) |
| **集成测试** | `POST /files/upload` 异步流程 | 上传后 Document.status=pending, Task.status=pending, 后台执行后变为 completed |
| **集成测试** | `GET /tasks/{id}` 轮询 | 查询任务状态、错误信息 |
| **集成测试** | `POST /documents/{id}/process` 异步 | 创建任务、后台向量化、防重复 |
| **集成测试** | 错误路径 | mock process_document 抛异常，验证 Task.status=failed + error_message |
| **集成测试** | 防重复 | 同一文件上传两次，第二次返回现有 task_id |

## 验收标准

- [ ] `POST /files/upload` 返回 `task_id`，Document 状态为 `pending`
- [ ] 后台任务完成后，Document.status = `completed`，Task.status = `completed`
- [ ] 后台任务失败时，Task.status = `failed`，有明确 error_message
- [ ] `GET /tasks/{id}` 能正确查询任务状态
- [ ] `GET /tasks` 支持按 status 过滤，结果按 knowledge_base 隔离
- [ ] `POST /documents/{id}/process` 从同步改为异步
- [ ] 同一 document 的重复 process 请求返回现有进行中 task_id
- [ ] 所有接口受 RBAC 保护，跨知识库返回 404
- [ ] TaskService 状态机有完整单元测试覆盖
- [ ] 异步流程的集成测试覆盖成功和失败路径
