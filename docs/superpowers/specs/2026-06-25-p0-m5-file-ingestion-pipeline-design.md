# P0-M5 文件摄取与解析管线设计

## 目标

让知识进入系统不再依赖手工粘贴纯文本，支持 PDF、DOCX、Markdown、HTML 和纯文本文件的上传、解析、创建 Document 和向量化。

M5 保持向量化同步执行（复用现有 `process_document`），但代码结构预留异步切换点。M6 将引入任务队列把向量化拆出 API 请求链路。

## 范围

- 新增文件上传 API，记录文件名、MIME type、size、hash、存储路径
- 支持 PDF、DOCX、Markdown、HTML、TXT 到文本的解析
- 解析结果转为 `Document`，保留文件来源 metadata
- 新增 `FileUpload` 模型，与 `Document` 分离
- 对解析失败记录错误原因，不创建半完成索引
- 为后续 OCR、网页抓取、企业系统连接器预留 parser 接口
- 为后续 S3/对象存储预留 storage 接口

## 不做

- 图片 OCR
- Confluence / 飞书 / 钉钉连接器
- 网页爬虫
- 异步向量化（M6 负责）
- 对象存储实现（仅预留接口）
- 一个文件生成多个 Document

## 依赖

- P0-M2 的租户 / 工作区 / 知识库模型（文件归属知识库）
- P0-M3 的 RBAC 权限（上传/读取/删除需鉴权）
- P0-M4 的向量库检索隔离（向量化结果正确归属知识库）

## 架构

新增两层服务和一个模型：

```
┌─────────────────────────────────────────────┐
│  API Layer                                  │
│  POST /api/v1/files/upload                  │
│  GET  /api/v1/files                         │
│  DELETE /api/v1/files/{id}                  │
└──────────────┬──────────────────────────────┘
               │
┌──────────────▼──────────────────────────────┐
│  IngestionService                           │
│  协调：存储 → 解析 → Document → 向量化         │
└──────────────┬──────────────────────────────┘
               │
    ┌──────────┴──────────┐
    ▼                     ▼
┌─────────────┐    ┌──────────────┐
│ Storage     │    │ Parser       │
│ (抽象层)     │    │ (Registry)   │
│ 本地实现     │    │ PDF/DOCX/    │
│ 未来可切S3   │    │ MD/HTML      │
└─────────────┘    └──────────────┘
```

**核心原则**：

- `Document` 保留现有结构和 `process_document` 链路不变
- `FileUpload` 独立存在，Document 通过 `file_id` 外键关联（nullable，兼容旧文本创建）
- 解析器通过 `ParserRegistry` 按 `mime_type` 分发，新增格式只需注册新解析器
- 存储通过 `StorageBackend` 协议抽象，M5 实现 `LocalStorageBackend`

## 数据模型

### 新增 `FileUpload` 模型

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | CHAR(36) PK | UUID |
| `knowledge_base_id` | CHAR(36) FK → KnowledgeBase | 归属知识库，级联删除 |
| `original_name` | String(500) | 原始文件名 |
| `stored_name` | String(500) | 存储路径（相对路径，格式：`{kb_id}/{uuid}/{safe_filename}`） |
| `mime_type` | String(255) | MIME type |
| `size_bytes` | Integer | 文件大小 |
| `content_hash` | String(64) | SHA-256，用于去重检测 |
| `status` | Enum | `uploaded` / `parsed` / `error` |
| `error_message` | Text nullable | 解析失败原因 |
| `parsed_at` | DateTime nullable | 解析完成时间 |
| `created_at` | DateTime | server_default=func.now() |
| `updated_at` | DateTime | server_default=func.now(), onupdate=func.now() |

### `Document` 扩展

新增字段：

- `file_id: Mapped[str | None]` — 外键 → `FileUpload.id`，nullable，无数据库级联

关系：

- `file: Mapped[FileUpload | None]` — relationship，back_populates="document"

理由：

- 旧的手动文本创建（`POST /documents`）没有文件，`file_id` 为 NULL
- 文件上传创建的 Document 指向对应的 FileUpload
- 删除 Document 时**不级联删除** FileUpload（文件可在知识库文件列表中独立存在）
- 删除 FileUpload 时由 `IngestionService.delete_file()` 显式清理关联的 Document、chunks、vectors，不依赖数据库级联（因为 Document 也可能是独立创建的）

### 状态流转

```
上传完成 → FileUpload.status = uploaded
  ↓
解析文本 → 创建 Document
  ↓
向量化成功 → FileUpload.status = parsed, parsed_at = now
  ↓ (失败)
FileUpload.status = error, error_message = 原因
```

## 存储层

### 协议定义

```python
class StorageBackend(Protocol):
    """Abstract storage backend. M5 implements local filesystem."""

    async def save(self, file: UploadFile, path: str) -> str:
        """Save file, return stored path/identifier."""
        ...

    async def read(self, path: str) -> bytes:
        """Read file content as bytes."""
        ...

    async def delete(self, path: str) -> None:
        """Delete file."""
        ...

    def get_url(self, path: str) -> str | None:
        """Return public URL if available, else None."""
        ...
```

### M5 实现：`LocalStorageBackend`

- 基础目录由 `STORAGE_LOCAL_PATH` 配置（默认 `./data/uploads/`）
- 文件按 `{knowledge_base_id}/{uuid}/{safe_filename}` 组织，避免单目录膨胀
- `stored_name` 存相对路径，不暴露绝对路径
- `safe_filename` 过滤路径遍历字符（`..`、`/` 等）

### 未来扩展

增加 `S3StorageBackend` 只需：

1. 实现同一协议
2. 配置 `storage_backend = "s3"`
3. 切换 `get_storage_backend()` 工厂返回实例

现有 API 代码无需改动。

## 解析层

### 协议定义

```python
class DocumentParser(Protocol):
    """Parse file bytes to plain text."""

    @property
    def supported_mime_types(self) -> set[str]:
        """Return supported MIME types."""
        ...

    def parse(self, content: bytes, filename: str) -> str:
        """Parse file bytes to text. Raise ParseError on failure."""
        ...
```

### M5 支持格式

| 格式 | MIME type | 解析器 | 依赖 |
|---|---|---|---|
| PDF | `application/pdf` | `PyPDFParser` | `pypdf>=4.0` |
| Word | `application/vnd.openxmlformats-officedocument.wordprocessingml.document` | `DocxParser` | `python-docx>=1.1` |
| Markdown | `text/markdown`, `text/x-markdown` | `MarkdownParser` | 纯文本，无额外依赖 |
| HTML | `text/html` | `HTMLParser` | `beautifulsoup4>=4.12` |
| 纯文本 | `text/plain` | `PlainTextParser` | 无额外依赖 |

### ParserRegistry

```python
class ParserRegistry:
    """Register and dispatch parsers by MIME type."""

    def register(self, parser: DocumentParser) -> None: ...
    def get_parser(self, mime_type: str) -> DocumentParser: ...
    def is_supported(self, mime_type: str) -> bool: ...
    def list_supported_types(self) -> list[str]: ...
```

M5 启动时自动注册所有内置解析器。新增格式只需：

1. 实现 `DocumentParser` 协议
2. `registry.register(MyNewParser())`

### 异常

- `ParseError`：解析失败（损坏文件、不支持的子格式等），带明确错误信息
- `UnsupportedFileTypeError`：MIME type 不在任何解析器的 `supported_mime_types` 中

## API 端点与摄取服务

### 新增端点

| 方法 | 路径 | 说明 | 权限 |
|---|---|---|---|
| `POST` | `/api/v1/files/upload` | 上传文件，解析文本，创建 Document，触发向量化 | `document:write` |
| `GET` | `/api/v1/files` | 列出知识库的文件上传记录 | `document:read` |
| `GET` | `/api/v1/files/{file_id}` | 获取单个文件上传记录 | `document:read` |
| `DELETE` | `/api/v1/files/{file_id}` | 删除文件及关联的 Document、chunk、向量 | `document:delete` |

### `POST /api/v1/files/upload` 流程

```
1. 校验：文件大小 ≤ MAX_UPLOAD_SIZE（默认 50MB）
2. 校验：mime_type 在 ParserRegistry 支持列表中
3. 计算：content_hash = SHA-256(file_content)
4. 去重：按配置策略处理重复 hash
5. 存储：StorageBackend.save() → 得到 stored_name
6. DB：创建 FileUpload 记录（status = uploaded）
7. 解析：ParserRegistry.get_parser(mime_type).parse() → text
8. DB：创建 Document（content = 解析文本, file_id = FileUpload.id）
9. 向量：调用现有 process_document() 同步 chunk + embedding
10. DB：更新 FileUpload.status = parsed, parsed_at = now
11. 返回：FileUpload + Document 信息
```

### `IngestionService` 职责

```python
class IngestionService:
    """Orchestrate file upload → storage → parse → document → vectorize."""

    def __init__(
        self,
        storage: StorageBackend,
        parser_registry: ParserRegistry,
        processor: DocumentProcessor,
    ):
        ...

    async def ingest_file(
        self,
        db: Session,
        file: UploadFile,
        knowledge_base_id: str,
    ) -> FileUpload:
        """Full ingestion pipeline."""
        ...

    async def delete_file(
        self,
        db: Session,
        file_id: str,
        knowledge_base_id: str,
    ) -> None:
        """Delete file, document, chunks, vectors."""
        ...
```

### 异常回滚

- 步骤 1–5 失败：无 DB 写入，无残留
- 步骤 6 解析失败：FileUpload.status = error，记录 error_message，**不创建 Document**
- 步骤 7–9 失败：FileUpload.status = error，**已创建的 Document 需要回滚删除**（事务或显式清理）
- 步骤 5 存储成功但后续失败：需要删除已存储的文件

### 重复文件处理策略

配置项 `UPLOAD_DUPLICATE_POLICY`：

- `reject`（默认）：返回 409，提示文件已存在
- `replace`：删除旧 FileUpload + Document，重新导入

M5 先实现 `reject`，`replace` 预留接口。

## 配置

`apps/luna-corpus/app/core/config.py` 新增：

| 配置项 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `STORAGE_BACKEND` | str | `local` | 存储后端类型 |
| `STORAGE_LOCAL_PATH` | str | `./data/uploads` | 本地存储基础目录 |
| `MAX_UPLOAD_SIZE` | int | `52428800`（50MB） | 最大上传字节数 |
| `UPLOAD_DUPLICATE_POLICY` | str | `reject` | 重复文件策略 |

## 错误处理

| 场景 | 行为 | HTTP 状态码 |
|---|---|---|
| 文件超过大小限制 | 拒绝上传，返回 `max_size` 限制 | `413` |
| 不支持的 MIME type | 拒绝上传，返回支持的类型列表 | `415` |
| 文件损坏/解析失败 | FileUpload.status = `error`，记录原因，不创建 Document | `422` |
| 向量化失败 | FileUpload.status = `error`，回滚已创建的 Document | `500` |
| 重复文件（hash 相同） | 按配置策略拒绝或覆盖 | `409` 或 `200` |
| 知识库不存在/无权限 | 现有 RBAC 层处理 | `403` / `404` |
| 文件不存在/跨知识库 | 现有 RBAC + 知识库过滤处理 | `404` |

## 主要改动点

- 新增 `apps/luna-corpus/app/services/ingestion/` 目录：
  - `__init__.py`
  - `storage.py` — StorageBackend 协议 + LocalStorageBackend
  - `parsers.py` — DocumentParser 协议 + 各格式解析器 + ParserRegistry
  - `service.py` — IngestionService
- `apps/luna-corpus/app/db/models.py` — 新增 FileUpload 模型，Document 增加 file_id
- `apps/luna-corpus/app/api/routes.py` — 新增文件上传/列表/删除端点
- `apps/luna-corpus/app/core/config.py` — 新增存储和上传配置
- `apps/luna-corpus/pyproject.toml` — 新增依赖：`pypdf`, `python-docx`, `beautifulsoup4`
- Alembic migration 文件

## 测试

### 测试分层

| 层级 | 目标 | 关键用例 |
|---|---|---|
| **单元测试** | Parser 正确性 | PDF/DOCX/MD/HTML/TXT 各至少一个 fixture，验证文本提取 |
| **单元测试** | StorageBackend | LocalStorageBackend save/read/delete/get_url |
| **单元测试** | ParserRegistry | 注册、分发、不支持类型异常 |
| **单元测试** | IngestionService | 完整流程 mock（mock storage + mock parser + mock processor） |
| **集成测试** | API 端点 | 上传、列表、删除，验证 DB 状态流转 |
| **集成测试** | 错误路径 | 损坏文件、超大文件、不支持类型、重复 hash |

### Fixture 策略

- `tests/fixtures/sample.pdf` — 小型有效 PDF（1–2 页）
- `tests/fixtures/sample.docx` — 小型 Word 文档
- `tests/fixtures/sample.md` — Markdown 文件
- `tests/fixtures/sample.html` — HTML 文件
- `tests/fixtures/corrupted.pdf` — 故意损坏的文件

### 权限测试

复用现有 RBAC 测试模式：

- 匿名用户 → `403`
- viewer → `GET` 可，`POST/DELETE` 被 `403`
- member/admin/owner → 正常操作
- 跨知识库文件 ID → `404`

## 验收标准

- [ ] 用户可上传 PDF/DOCX/Markdown/HTML/TXT 文件到指定知识库
- [ ] 上传后系统能生成对应 Document，并保留文件来源和 hash
- [ ] 不支持的文件类型被拒绝并返回明确错误
- [ ] 解析失败不会产生半完成索引
- [ ] 删除文件会级联清理关联的 Document、chunk、向量
- [ ] 重复文件按配置策略正确处理
- [ ] 所有接口受 RBAC 保护，跨知识库访问返回 404
- [ ] 每种支持格式至少一个解析单元测试
- [ ] 错误路径（损坏、超大、不支持、重复）有测试覆盖
