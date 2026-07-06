# 混合检索（Hybrid Retrieval）设计

- 日期：2026-07-06
- 应用：`apps/luna-corpus`
- 背景：`LUNA_CORPUS_ENTERPRISE_RAG_GAP_ANALYSIS.md` 将「混合检索」列为 P1 项——当前只有向量检索，缺少关键词/BM25 融合。企业文档中的编号、术语、人名、代码常需要 lexical search。

## 目标

在现有纯向量检索之外新增一路 BM25 关键词检索，用 RRF 融合两路结果，通过配置开关控制启用，且对现有调用方改动最小。

## 关键决策

| 决策点 | 选择 | 理由 |
| --- | --- | --- |
| 关键词检索后端 | 纯 Python BM25（`rank-bm25` + `jieba` 中文分词） | 零新增基础设施，匹配当前轻量单体阶段；中文分词可控 |
| 融合策略 | RRF（Reciprocal Rank Fusion） | 无需归一化/调参、对分数量纲不敏感、工业界默认、鲁棒 |
| 上线方式 | 可配置开关 `retrieval_mode`（`vector`/`hybrid`） | 可灰度、可回滚，保留纯向量 fallback；与现有可配置后端风格一致 |
| BM25 索引生命周期 | 按 knowledge_base 懒加载 + 内存缓存 | 内存按需、KB 隔离、实现简单 |
| 缓存失效 | 索引任务完成后主动失效 + 兜底 TTL | 新文档立即可被关键词命中，同时有兜底 |
| 默认模式 | `hybrid` | 这是本次交付的核心功能，`vector` 作为回滚项保留 |

## 架构

```
                          retrieve_node / rag_search 工具
                                     │
                          ┌──────────┴──────────┐
                          │  hybrid_search()     │  ← 新增，检索编排层
                          │  (app/retrieval/)    │
                          └──────────┬──────────┘
              retrieval_mode=hybrid  │  retrieval_mode=vector
                   ┌─────────────────┴─────────────────┐
                   ▼                                     ▼
         ┌──────────────────┐               ┌──────────────────┐
         │ 向量检索(已有)     │               │ 仅走向量 (fallback) │
         │ search_vectorstore│               └──────────────────┘
         └────────┬─────────┘
                  │        ┌──────────────────────┐
                  │        │ BM25 关键词检索(新增)  │
                  │        │ Bm25Index + jieba     │
                  │        │ 按 KB 缓存, 主动失效   │
                  │        └──────────┬───────────┘
                  └──────────┬────────┘
                             ▼
                   ┌──────────────────┐
                   │ RRF 融合排序(新增) │
                   └──────────────────┘
```

**新增模块目录 `app/retrieval/`**（把检索编排从 `db/vectorstore.py` 分离，保持单一职责）：

- `app/retrieval/bm25.py` — BM25 索引：按 KB 加载 chunk 文本、jieba 分词、缓存、失效
- `app/retrieval/fusion.py` — RRF 融合算法（纯函数）
- `app/retrieval/hybrid.py` — `hybrid_search` 编排：根据 `retrieval_mode` 调度向量/BM25/融合

**保持不动**：`app/db/vectorstore.py` 的向量检索原样保留，作为其中一路被调用。

## 核心组件与接口

### `app/retrieval/bm25.py`

```python
@dataclass(frozen=True)
class Bm25Result:
    chunk_id: str
    document_id: str
    content: str
    score: float

class Bm25Index:
    """单个 knowledge base 的 BM25 内存索引。"""
    def search(self, query: str, top_k: int) -> list[Bm25Result]: ...

# 模块级缓存 + 失效
def get_bm25_index(kb_id: str) -> Bm25Index      # 懒加载，缓存命中直接返回
def invalidate_bm25_cache(kb_id: str) -> None    # 供 ingestion 钩子调用
def reset_bm25_cache() -> None                   # 供测试用

def _tokenize(text: str) -> list[str]            # jieba.lcut_for_search + 去停用词/空白
def _build_index(kb_id: str) -> Bm25Index        # 从 MySQL 读该 KB 全部 chunk 文本构建
```

- 缓存结构：`dict[kb_id -> (Bm25Index, built_at_timestamp)]`，带兜底 TTL（`bm25_cache_ttl_seconds`）
- 从 MySQL 读取：`Chunk JOIN Document WHERE Document.knowledge_base_id == kb_id`（与向量检索的 KB 隔离一致）
- 空 KB（无 chunk）返回空索引，`search` 返回 `[]`
- 内置精简中英文停用词集合（模块常量），不外挂文件

### `app/retrieval/fusion.py`

```python
def reciprocal_rank_fusion(
    result_lists: list[list[dict]],   # 多路结果，每路已按各自分数排序
    k: int = 60,                      # RRF 常数，配置项
    top_k: int = 5,
) -> list[dict]:
    """按 chunk_id 聚合，score = Σ 1/(k + rank)，返回融合后 top_k。"""
```

- 纯函数，输入输出为标准 dict（`chunk_id`/`document_id`/`content`/`score`），无副作用
- 输出 `score` 替换为 RRF 分数；可选保留原始两路分数到 metadata，便于调试/未来 rerank

### `app/retrieval/hybrid.py`

```python
def hybrid_search(
    query: str,
    query_embedding: list[float],
    *,
    top_k: int,
    knowledge_base_id: str,
) -> list[dict]:
    """根据 settings.retrieval_mode 调度：
       - vector: 只调 search_vectorstore（现有行为）
       - hybrid: 向量 + BM25 各取 candidate_k，RRF 融合后取 top_k
    """
```

- 返回格式与现有 `search_vectorstore` **完全一致**（`list[dict]`，含 `chunk_id/document_id/content/score`），调用方改动最小
- `hybrid` 模式下每路先各取 `candidate_k`（`retrieval_candidate_k`）再融合

## 调用点接入

把 `search_vectorstore` 换成 `hybrid_search`（hybrid 需 query 文本 + embedding 两个入参）：

1. **`app/graph/rag_graph.py`** — 3 处：`retrieve_node`、`answer_question_stream`、`answer_question_multi_turn_stream`。每处保留 `embed_text(question)`，将 `search_vectorstore(query_embedding, top_k, kb_id)` 换为 `hybrid_search(question, query_embedding, top_k=..., knowledge_base_id=...)`。`validate_retrieved_docs_for_knowledge_base`、`format_sources` 不变。
2. **`app/agent/tools/rag_search.py`** — `_format_rag_results`：同样换成 `hybrid_search`，传入 query 文本。

缓存失效钩子（主动失效）：

3. **`app/services/document_processor.py`**（`process_document`，约 line 122）— 在 `add_chunks_to_vectorstore(...)` 之后调用 `invalidate_bm25_cache(knowledge_base_id)`（从 document 取 `knowledge_base_id`）。
4. **`app/services/ingestion/service.py`**（`delete_file`，约 line 261）— 在 `delete_chunks_from_vectorstore(...)` 之后调用 `invalidate_bm25_cache(knowledge_base_id)`（该处已有 `knowledge_base_id` 参数）。

流式提示：`answer_question_stream` 里 `"正在检索相似文档..."` 在 hybrid 模式下改为 `"正在进行混合检索（向量 + 关键词）..."`。

### 数据流（hybrid，一次问答）

```
question ──> embed_text ──> query_embedding
   │                              │
   │                              ▼
   │                    向量检索 candidate_k 条
   ▼
BM25 (jieba分词) ──> 关键词检索 candidate_k 条
              │            │
              └──> RRF 融合 ──> top_k ──> validate_kb ──> format ──> LLM
```

## 配置项（`app/core/config.py`，`# RAG` 区块）

```python
class RetrievalMode(str, enum.Enum):
    VECTOR = "vector"
    HYBRID = "hybrid"

retrieval_mode: RetrievalMode = Field(
    default=RetrievalMode.HYBRID,
    description="检索模式：vector 仅向量；hybrid 向量+BM25 融合",
)
retrieval_candidate_k: int = Field(
    default=20, description="hybrid 模式下每路检索的候选数量"
)
rrf_k: int = Field(default=60, description="RRF 融合常数")
bm25_cache_ttl_seconds: int = Field(
    default=600, description="BM25 索引缓存兜底过期时间（秒）"
)
```

（`retrieval_top_k` 已存在，复用为最终返回数量。）

新增依赖（`pyproject.toml`）：`rank-bm25`、`jieba`。

## 错误处理

原则：**BM25 一路失败不能拖垮问答。**

- **BM25 异常**（DB 读失败、jieba 异常）：`hybrid_search` 内 try/except 捕获，降级为纯向量结果，记结构化 `logger.warning`（带 `kb_id`），问答不中断。
- **向量异常**：向上抛出（与现状一致，向量是必需路径）。
- **空结果**：任一路空 → 融合自然处理；两路都空 → 返回 `[]`，下游 `generate_node` 已有「找不到相关信息」分支。
- **jieba**：`import jieba` 置于模块顶部；分词对空 query / 全停用词 query 返回 `[]`，BM25 直接返回空。

## 可观测性

复用 P0-M8 的 metrics 风格。第一版：在 `hybrid_search` 用现有 `time_stage(RAG_RETRIEVAL_DURATION)` 包裹整体。BM25 子阶段单独计时、`mode` label 区分列为可选后续。

## 测试策略

新增 `tests/retrieval/`，大量使用内存小语料 + fake embedding，避免依赖真实 Chroma/LLM。

### `tests/retrieval/test_fusion.py`（纯单元）
- RRF 基础聚合：`score = Σ 1/(k+rank)`
- 同一 chunk 两路都出现 → 分数累加、排名提升
- 单路为空 → 退化为另一路排序
- 两路都空 → `[]`
- `top_k` 截断正确
- 保留原始分数到 metadata（若实现）

### `tests/retrieval/test_bm25.py`
- `_tokenize`：中文分词 + 去停用词；空/全停用词 query → `[]`
- `Bm25Index.search`：关键词命中的 chunk 排在前
- 缓存命中：连续两次 `get_bm25_index` 只构建一次
- `invalidate_bm25_cache`：失效后重新构建
- TTL 兜底过期
- 空 KB → 空索引，`search` 返回 `[]`

### `tests/retrieval/test_hybrid.py`
- `retrieval_mode=vector`：只调向量，等同现有 `search_vectorstore`
- `retrieval_mode=hybrid`：两路都调、走 RRF、返回格式一致
- 降级测试：BM25 抛异常 → 返回纯向量结果 + warning（不抛）
- candidate_k / top_k 传递正确

### 回归 / 集成
- 现有 `tests/db/test_vectorstore.py`、`tests/api/test_audit_qa_index.py` 继续通过
- ingestion：验证 `process_document` / `delete_file` 后 `invalidate_bm25_cache` 被调用（spy）

## 非目标（YAGNI）

- rerank（cross-encoder / LLM rerank）——独立的后续 P1 项
- 加权分数融合、A/B 实验分流——RRF 稳定后再评估
- OpenSearch/Elasticsearch 等外部 lexical 引擎——中期基础设施决策
- BM25 索引持久化 / 多实例共享——当前进程内缓存可重建，够用
