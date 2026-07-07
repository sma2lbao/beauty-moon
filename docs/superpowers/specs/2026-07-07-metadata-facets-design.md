# 元数据与分面过滤模块设计

- **日期**：2026-07-07
- **范围**：仅后端（`apps/luna-corpus`）；前端（上传表单、筛选侧边栏、分面 UI）留待后续独立 spec
- **状态**：已评审通过，待实现

## 1. 背景与目标

Luna Corpus 已具备混合检索（向量 + BM25 + RRF）与重排。当前检索只按 `knowledge_base_id` 做隔离，无法按业务维度收窄；`Chunk.chunk_metadata`（JSON）始终为空，`Document` 仅有 `title`/`source`/`has_tables`/`has_code` 等技术字段。

本模块引入**知识库级元数据 Schema**、**分面过滤检索**与**全库分面聚合**，让用户可按业务维度（类别、部门、日期、标签、数值等）筛选检索，并为前端提供筛选器数据源。

目标拆为四块：

1. **元数据 Schema**：每个知识库可定义一组可筛选字段（类型化）。
2. **摄取录入**：上传时按 schema 校验并归一化业务元数据，存库并传播到向量库。
3. **分面聚合**：按知识库统计各维度各取值的文档命中数（全库口径），供前端做筛选器。
4. **过滤检索**：检索时按元数据条件收窄，向量侧下推 Chroma `where`、BM25 侧 post-filter。

## 2. 整体架构与模块边界

### 新增模块

```
app/metadata/                 ← 元数据 Schema 与校验
├── __init__.py               ← 包 docstring + 导出
├── models.py                 ← MetadataFieldDefinition ORM
├── schema.py                 ← FieldType 枚举、字段定义的 Pydantic 模型
├── validation.py             ← 按 schema 校验 + 归一化上传元数据
└── facets.py                 ← 全库分面聚合（SQL GROUP BY + Python 聚合）

app/retrieval/filters.py      ← MetadataFilter 模型 + 翻译成 Chroma where / post-filter 谓词
```

### 改动的既有模块

- `db/models.py`：新增 `MetadataFieldDefinition` 表；`Document` 增 `doc_metadata`(JSON) 列。
- `db/vectorstore.py`：`VectorChunkInput`/`add_chunks` 携带业务元数据写入 Chroma；`search` 接受额外 `where` 过滤条件。
- `retrieval/hybrid.py`：`hybrid_search` 增 `filters` 参数——向量侧下推 `where`，BM25 侧 post-filter（over-fetch 补偿）。
- `api/routes.py`：新增 Schema 管理端点、分面端点；`/files`、`/documents` 接收元数据；`/qa/*` 系列与 agent `rag_search` 接收 `filters`。
- `services/document_processor.py` 与 `services/ingestion/`：把文档元数据带入 chunk 写向量库。
- `core/config.py`：新增 `filter_over_fetch_multiplier`。
- `observability/metrics.py`：新增 `rag_facet_duration_seconds`。

### 数据流

1. **定义**：管理员为知识库定义字段（`category` 枚举、`published_at` 日期…）。
2. **摄取**：上传带元数据 → 按 schema 校验归一化 → 存 `Document.doc_metadata` → 处理时随 chunk 写入 Chroma metadata。
3. **分面**：前端进库先调分面端点 → 按知识库聚合出「各维度各取值命中文档数」。
4. **检索**：用户选定筛选 → `filters` 透传到 `hybrid_search` → 向量侧 Chroma `where` 下推 + BM25 侧 post-filter → 融合返回。

### 边界原则

- `app/metadata` 只管「字段定义 + 校验 + 分面聚合」，不碰检索。
- `app/retrieval/filters.py` 只管「把过滤条件翻译成 Chroma where 与 post-filter 谓词」，不碰 schema 存储。
- 两者通过 `MetadataFilter` / 字段定义数据结构解耦。

## 3. 元数据 Schema 模型与字段类型

### `MetadataFieldDefinition` 表

| 列 | 类型 | 说明 |
|---|---|---|
| `id` | CHAR(36) | 主键 |
| `knowledge_base_id` | CHAR(36) FK | 归属知识库，`ondelete=CASCADE` |
| `key` | String(64) | 字段标识，如 `category`；库内唯一 |
| `label` | String(255) | 展示名，如「文档类别」 |
| `field_type` | Enum | `enum`/`string`/`date`/`number`/`tags` |
| `options` | JSON, nullable | `enum`/`tags` 的候选值列表（可选，用于校验与前端下拉） |
| `required` | Boolean | 上传时是否必填，默认 `False` |
| `is_facetable` | Boolean | 是否参与分面聚合，默认 `True` |
| `created_at`/`updated_at` | DateTime | 时间戳 |

约束：`UniqueConstraint(knowledge_base_id, key)`。

### `FieldType` 枚举与语义

| 类型 | 存储形态 | 过滤操作符 | 分面方式 |
|---|---|---|---|
| `enum` | str | 等值 / 多选(in) | 按值计数 |
| `string` | str | 等值 | 按值计数（Top-N） |
| `date` | ISO 字符串 `YYYY-MM-DD` | 区间(gte/lte) | 按月分桶计数 |
| `number` | float | 区间(gte/lte) | 等宽区间分桶 |
| `tags` | list[str] | 包含(任一/全部) | 按标签计数 |

### Chroma 存储适配（关键约束）

Chroma 的 metadata 值只支持标量（str/int/float/bool），**不支持 list**。映射规则集中在 `retrieval/filters.py`：

- `enum`/`string`：原样存 str。
- `date`：存 `YYYY-MM-DD` 字符串（字典序等价日期序，可用 `$gte`/`$lte`）。
- `number`：存 float。
- `tags`：**布尔展开**——每个标签存为 `tag__<value> = True`。过滤「包含 X」即 `where={"tag__X": True}`。

### Schema 管理 API（前缀 `/api/v1`）

- `POST /knowledge-bases/{kb_id}/metadata-fields` 创建字段 — 需 `knowledge_base:manage`
- `GET /knowledge-bases/{kb_id}/metadata-fields` 列出字段 — 需 `knowledge_base:read`
- `PATCH /metadata-fields/{field_id}` 改 label/options/required/is_facetable — 需 `knowledge_base:manage`
- `DELETE /metadata-fields/{field_id}` 删除字段 — 需 `knowledge_base:manage`

### 演进策略（YAGNI）

删除/改字段类型**不回溯清洗**历史文档的 `doc_metadata`（历史值保留，聚合/过滤只按当前字段定义呈现）。避免引入重索引负担，符合「本次聚焦、可独立实现」。

## 4. 摄取时的元数据录入与校验

### 录入通道

- `POST /files`（文件上传）——新增可选表单字段 `metadata`（JSON 字符串）。
- `POST /documents`（直接建文档）——请求体新增可选 `metadata` 对象。

示例：`{"category":"合同","tags":["2025","采购"],"published_at":"2025-03-01"}`

### 校验与归一化（`app/metadata/validation.py`）

```
validate_and_normalize(kb_id, raw_metadata, db) -> normalized: dict
```

1. 加载该知识库的字段定义。
2. **必填校验**：`required=True` 的字段缺失 → 抛 `MetadataValidationError`（422）。
3. **未知字段**：出现未定义 key → 拒绝（422），保证维度干净（严格模式）。
4. **按类型归一化**：
   - `enum`：值须在 `options` 内（若定义）；trim。
   - `string`：trim。
   - `date`：解析为 `YYYY-MM-DD`，非法格式报错。
   - `number`：转 float，非数值报错。
   - `tags`：转 `list[str]`，逐个 trim、去空、去重；若定义 options 则每个标签须在其中。
5. 返回归一化后的 dict。

### 校验时机与一致性

在 `IngestionService.ingest_file` / `create_document` 里，**存文档前**校验。校验失败 → 整个上传失败（文件不落库、不产生半成品）。

### 元数据 → 向量库传播

- `document_processor.process_document` 读取 `Document.doc_metadata`，随每个 chunk 写入 Chroma（经 `filters.py` 映射：tags 布尔展开、date/number 转标量）。
- `Chunk.chunk_metadata` 同时存一份原始归一化值（供 post-filter 与调试）。
- BM25 命中结果携带 `chunk_metadata`（从 DB / 索引项读取），供 `hybrid.py` 中 post-filter 判定。

## 5. 检索过滤 API 与执行链路

### 过滤条件数据结构（`app/retrieval/filters.py`）

```python
class FilterOp(StrEnum):
    EQ = "eq"; IN = "in"          # enum/string
    GTE = "gte"; LTE = "lte"      # date/number 区间
    CONTAINS_ANY = "contains_any" # tags 任一
    CONTAINS_ALL = "contains_all" # tags 全部

class MetadataCondition(BaseModel):
    key: str
    op: FilterOp
    value: str | float | list[str]

class MetadataFilter(BaseModel):
    conditions: list[MetadataCondition]   # 多条件之间 AND
```

多条件 **AND** 组合（YAGNI：不做 OR / 嵌套布尔）。

### 两种执行形式（同一 `MetadataFilter` 翻译两次）

- `to_chroma_where(filter, field_defs) -> dict`：向量侧下推。
  - `eq → {k: v}`
  - `in → {k: {"$in": [...]}}`
  - `gte/lte → {k: {"$gte": v}}` / `{k: {"$lte": v}}`
  - `contains_any → {"$or": [{"tag__x": True}, ...]}`
  - `contains_all → {"$and": [{"tag__x": True}, ...]}`
  - 多条件与 kb 隔离条件一起包进顶层 `{"$and": [...]}`。
- `make_post_filter(filter, field_defs) -> Callable[[dict], bool]`：BM25 侧谓词，读候选 `chunk_metadata` 判定。

### `hybrid_search` 改动

```python
def hybrid_search(query, query_embedding, *, top_k, knowledge_base_id, filters=None):
```

- 向量侧：`where` 合并「kb 隔离 + filters 下推」，一次查询即过滤。
- BM25 侧：正常召回后用 `post_filter` 剔除；有 filters 时候选窗口按 `filter_over_fetch_multiplier`（默认 3）放大，再融合截断到 `top_k`。
- **无 `filters` 时行为与现状完全一致（零回归）**。

### 检索 API 改动

`/qa/query`、`/qa/stream`、`/qa/multi-turn`（及其 stream）与 agent 的 `rag_search` 工具请求体新增可选 `filters` 字段，透传到 `hybrid_search`。检索读权限沿用 `qa:query`。

### 分面端点

`GET /api/v1/knowledge-bases/{kb_id}/facets` — 需 `knowledge_base:read`。对 `is_facetable=True` 的字段，聚合 `Document.doc_metadata`，返回各维度各取值的文档计数（分桶规则见第 6 节）。

## 6. 分面聚合计算细节

### 端点

`GET /api/v1/knowledge-bases/{kb_id}/facets`

### 响应结构

```json
{
  "facets": [
    {
      "key": "category", "label": "文档类别", "field_type": "enum",
      "buckets": [
        {"value": "合同", "count": 12},
        {"value": "发票", "count": 5}
      ]
    },
    {
      "key": "published_at", "label": "发布日期", "field_type": "date",
      "buckets": [
        {"value": "2025-03", "count": 8},
        {"value": "2025-02", "count": 4}
      ]
    }
  ]
}
```

### 分桶规则

| 类型 | 分桶方式 | count 口径 |
|---|---|---|
| `enum` | 每个取值一个桶 | 该值的文档数 |
| `string` | 每个去重值一个桶，按 count 降序取 **Top-20**（避免高基数爆炸） | 文档数 |
| `tags` | 每个标签一个桶（多标签文档计入多个桶） | 含该标签的文档数 |
| `date` | 按**月**（`YYYY-MM`）分桶，降序 | 文档数 |
| `number` | 等宽区间分桶（默认 **5** 桶，跨度按 min/max 动态算） | 文档数 |

### 计算实现

- 数据源 `Document.doc_metadata`（JSON 列），按 `knowledge_base_id` 过滤。
- `enum`/`string`/`date` 优先用 MySQL `JSON_EXTRACT` + `GROUP BY` 下推 SQL；`tags`（数组展开）与 `number`（区间）在 Python 层聚合（一次性拉出该库文档的 `doc_metadata` 做内存聚合）。
- 只统计 `status=COMPLETED` 的文档。
- 空值（未填该字段）不计入桶；`null_count` 暂不实现（YAGNI）。

### 性能

分面为「进库时」低频调用，非热路径。先用简单实现；`is_facetable=False` 可关高基数字段。不引入缓存（YAGNI）。

## 7. 错误处理

| 场景 | 处理 |
|---|---|
| 上传元数据校验失败（必填缺失/未知字段/类型错误） | `MetadataValidationError` → 422，含字段与原因；整个上传回滚 |
| 创建字段时 `key` 重复 | 409 Conflict |
| 检索 `filters` 引用未定义字段 | 400，提示字段未定义 |
| 分面/过滤时 Chroma `where` 构造异常 | 记日志，检索**降级为无过滤**，响应标注过滤未生效（呼应现有「检索永不因辅助功能崩」哲学） |
| 字段被删后历史文档仍有该键 | 不报错，聚合/过滤按当前字段定义忽略 |

## 8. 数据库迁移

alembic 迁移 `20260707_0007_metadata_facets.py`：

- 新增 `metadata_field_definitions` 表。
- `documents` 增 `doc_metadata` JSON 列（nullable）。
- **无数据回填**（历史文档 `doc_metadata=NULL`，等同「无元数据」）。

## 9. 可观测性

复用现有 structlog + prometheus：

- 新增指标 `rag_facet_duration_seconds`（分面聚合耗时）。
- 检索过滤日志：`filter_applied` / `filter_degraded_no_op`。

## 10. 配置

`app/core/config.py` 新增：

- `filter_over_fetch_multiplier: int = 3`（有 filters 时放大 BM25/向量候选窗口以补偿过滤损耗）。

## 11. 测试策略

pytest，贴合现有 `tests/` 结构：

- `validation.py`：各类型校验/归一化、必填、未知字段拒绝、tags 去重。
- `filters.py`：`to_chroma_where` 各操作符映射（tags 布尔展开、date 字典序、多条件 AND）、`make_post_filter` 谓词。
- `facets.py`：各类型分桶、Top-N 截断、date 按月、number 等宽、仅 COMPLETED。
- `hybrid.py`：有/无 filters 检索（含无 filters 零回归断言）、over-fetch 补偿、Chroma where 异常降级。
- API 集成：Schema CRUD、带元数据上传（成功/422）、带 filters 检索、分面端点。

## 12. RBAC 映射汇总

| 操作 | 权限 slug |
|---|---|
| 创建/修改/删除元数据字段 | `knowledge_base:manage` |
| 列出元数据字段 | `knowledge_base:read` |
| 带元数据上传/建文档 | `document:write`（沿用现有上传权限） |
| 读取分面 | `knowledge_base:read` |
| 带 filters 检索 | `qa:query`（沿用现有检索权限） |
