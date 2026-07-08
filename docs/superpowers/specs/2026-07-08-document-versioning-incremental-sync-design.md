# 文档变更检测与增量索引 设计文档

- 日期：2026-07-08
- 主题：文档版本与增量同步 —— 子系统 1（变更检测与增量索引）
- 状态：已评审，待实现
- 适用应用：`apps/luna-corpus`

## 背景

缺口分析（`LUNA_CORPUS_ENTERPRISE_RAG_GAP_ANALYSIS.md:379`）将「文档版本与增量同步」列入 P1／阶段 2（可运营知识摄取）。当前问题：

- `Document` 只有 `updated_at`，没有版本、内容 hash、外部标识；每次上传都新建一份文档。
- 重复上传浪费 embedding 成本，旧版本内容会污染检索。
- 「更新一个文档」没有清晰入口：上传走 `/files/upload`（每次新建），重复文件由 `duplicate_policy`（reject/replace）处理；`/documents/{id}/process` 只做重新处理。

「文档版本与增量同步」整体包含三个相对独立的子系统，本 spec 只聚焦第一个（其余各自单独 spec → plan → 实现）：

1. **变更检测与增量索引（本次）** —— 地基，`content_hash` 驱动去重与更新。
2. **版本历史与回滚** —— 引入 `DocumentVersion` 快照，支持查看/对比/回滚。
3. **外部数据源增量同步** —— `external_id` + `sync_cursor` + 连接器抽象，定期拉取增量。

## 目标与范围

### 本次做（In scope）

- 文档身份概念：`document_id` > `external_id` > `original_name`（同一 KB 内）三级匹配。
- 文档级内容 hash（`content_hash`）比对，产出三态：`created` / `updated` / `unchanged`。
- 原地更新语义：`version` 单调递增计数器，不留历史；旧 chunks 删除重建、旧存储文件删除。
- 显式更新接口 `PUT /documents/{id}` + 重新上传自动匹配。
- 更新走现有异步索引链路（`IngestionTask` + `process_document`）。
- 移除旧的全局 hash 去重逻辑与 `duplicate_policy` 配置。

### 本次不做（Out of scope）

- 版本历史与回滚（子系统 2）。
- 外部连接器与 `sync_cursor` 拉取同步（子系统 3）。
- chunk 级增量 embedding（切分漂移导致收益不稳定，YAGNI）。

## 数据模型变更

### `Document` 表新增字段（Alembic 迁移，禁用生产 `create_all`）

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `content_hash` | `String(64)`, nullable | 文档解析后正文（`content`）的 SHA-256。存量文档为 NULL，首次更新命中时回填。 |
| `version` | `Integer`, not null, default 1 | 单调递增计数器。新建=1，每次内容变更 +1，`unchanged` 不变。 |
| `external_id` | `String(255)`, nullable | 可选业务标识，用于身份匹配。 |

### 约束

- 新增 `UniqueConstraint(knowledge_base_id, external_id)`：同一 KB 内 `external_id` 唯一（NULL 不参与唯一性，允许多个无 external_id 文档）。
- 文件名匹配不加 DB 唯一约束，仅在应用层查询匹配（存量同名数据可能多份，匹配取最新），避免存量迁移冲突。

### hash 口径

- `content_hash` 基于**解析后的 `Document.content`**，而非上传文件字节 —— 变更检测关心的是「进入检索的正文是否变化」。
- `FileUpload.content_hash`（文件字节 hash）保留不动，仅作文件层记录。

### 存量数据兼容

- 迁移只加列。`version` 默认 1，`content_hash`/`external_id` 为 NULL。存量文档首次被更新命中时自然回填 `content_hash`。

## 身份匹配与三态判定

### `resolve_document_identity()`

放在 ingestion service 层，在解析出正文、算出 `content_hash` 之后执行。

匹配顺序（同一 `knowledge_base_id` 内）：

1. 请求显式带 `document_id`（来自 `PUT /documents/{id}`）→ 按主键定位，找不到返回 404。
2. 否则请求带 `external_id` → 查 `Document.external_id == external_id`。
3. 否则用 `original_name` → 查该 KB 内 `title == original_name`，多条取 `updated_at` 最新一条。
4. 都未命中 → 全新文档。

### 三态判定

```
命中文档 existing:
    if existing.content_hash == new_content_hash:
        → unchanged：不动 Document，不建索引任务，返回 200
    else:
        → updated：原地更新 content / content_hash / version+1 / updated_at
                    （external_id 若本次带了则一并写入）
                    建 IngestionTask 异步重建 chunks，返回 200
未命中:
    → created：新建 Document（version=1，写入 content_hash / external_id）
                建 IngestionTask，返回 201
```

### 并发与竞态

- 同一 `external_id` 并发上传：DB 唯一约束兜底，并发 created 会有一方冲突 → 重试为 updated。
- 文件名路径无 DB 约束，属可接受的弱一致（极端并发下可能产生两条同名文档，与现状行为一致，不退化）。

### 旧逻辑移除

- `ingest_file` 中「按 content_hash 查任意 FileUpload + duplicate_policy」整段移除。
- `IngestionService.__init__` 的 `duplicate_policy` 参数、`get_settings().upload_duplicate_policy` 移除。
- `DuplicateFileError` 异常及其 409 分支废弃（`unchanged` 是正常响应，非错误）。

## API 契约变更

### 1. `POST /files/upload`（改动）

- 新增可选表单字段 `external_id`（与已有 metadata 并存）。
- 内部走身份匹配 + 三态判定。
- `FileUploadCreateResponse` 新增：`change_type`（`created`/`updated`/`unchanged`）、`version`（int）。
- 状态码：`created` → 201；`updated`/`unchanged` → 200。
- `unchanged` 时 `task_id` 为 null，`document_id` 仍返回命中文档 id。

### 2. `PUT /documents/{document_id}`（新增）

- 权限：`DOCUMENT_WRITE`。
- 请求体复用 `DocumentCreate`（`title`/`content`/`source`，可选 `external_id`）—— 粘贴新内容更新路径；文件更新仍走 `/files/upload`。
- 按 `document_id` 定位（跨 KB 越权则 404），比对 `content_hash` 出 `updated`/`unchanged`，异步重建。
- 响应 `DocumentResponse` 扩展 `version`、`change_type`。

### 3. `POST /documents`（改动，向后兼容）

- 新建时初始化 `version=1`、回填 `content_hash`、接受可选 `external_id`。
- 带的 `external_id` 已存在 → 409，detail 指明冲突文档 id 并建议改用 `PUT`。

### 4. 响应模型扩展

- `DocumentResponse` / `FileUploadCreateResponse` 统一新增 `version: int`、`external_id: str | null`；`change_type` 仅出现在写操作响应。

### 5. 移除

- `duplicate_policy` 配置与 `DuplicateFileError` 的 409 分支。

## 错误处理

- `PUT /documents/{id}` 命中不存在或跨 KB → 404。
- 新建路径 `external_id` 冲突 → 409，detail 指明冲突文档 id，建议改用更新。
- 更新时索引任务失败 → 沿用 M6：`Document.status=ERROR`、`IngestionTask.status=FAILED`。`content_hash`/`version` 在建任务前已提交（更新语义已生效），索引失败可重试 `process_document`，不回滚版本。
- `unchanged` 正常 200。
- 审计：`updated` 记 `DOCUMENT_UPDATE`，`created` 记 `DOCUMENT_CREATE`，`unchanged` 不记写操作。

## 测试策略

### 单元

- `resolve_document_identity()` 三级匹配优先级。
- 三态判定分支。
- `content_hash` 基于正文计算。

### 集成

- 同名文件重传：内容不变 → unchanged 不建任务；内容变 → updated version+1 重建 chunks。
- `external_id` 匹配优先于文件名。
- 换名传相同内容 → created（验证已移除全局去重）。
- `PUT /documents/{id}` 正常更新与 404 / 409。
- 存量文档（`content_hash=NULL`）首次更新回填。

### 回归

- 移除 `duplicate_policy` 后，既有上传测试更新到新语义。

## 文件落点

- `app/db/models.py`：`Document` 加 `content_hash` / `version` / `external_id` 字段与约束。
- `alembic/versions/`：新迁移脚本（加列 + 唯一约束）。
- `app/services/ingestion/service.py`：`resolve_document_identity()` + 三态逻辑，移除旧去重与 `duplicate_policy`。
- `app/services/document_processor.py`：无需改（已支持删旧建新）。
- `app/api/routes.py`：`/files/upload` 改造、新增 `PUT /documents/{id}`、`POST /documents` 调整、响应模型扩展。
- settings 配置：移除 `upload_duplicate_policy`。
- `tests/`：对应新增/更新。

## 数据流总览

```
上传/PUT → 解析正文 → 算 content_hash → resolve_identity
  ├ 未命中        → created  → 建 Document(v1) → IngestionTask → 异步重建
  ├ 命中&hash同   → unchanged→ 直接返回，无任务
  └ 命中&hash异   → updated  → 原地更新(v+1) → IngestionTask → 异步删旧建新
```
