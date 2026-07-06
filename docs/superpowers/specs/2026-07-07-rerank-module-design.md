# 重排（Rerank）模块设计

- **日期**：2026-07-07
- **目标应用**：`apps/luna-corpus`
- **状态**：已确认，待实现

## 一、背景与目标

现有检索链路为「向量 + BM25 → RRF 融合」，融合后直接截断到 `top_k` 送入
LLM 生成。本设计在融合之后增加**精排（rerank）**阶段：先粗召回较大的候选集，
再用交叉编码器（cross-encoder）按 query 相关性精排，提升送入 LLM 的上下文质量。

## 二、架构总览

形成逐级增强的三档检索模式，由 `retrieval_mode` 统一控制：

```
vector  → 仅向量召回 top_k
hybrid  → 向量 + BM25，RRF 融合出 top_k
rerank  → 向量 + BM25，RRF 融合出 candidate_k → 交叉编码器精排 → top_k
```

- `rerank` 模式完全复用 `hybrid` 的融合逻辑，区别仅在于融合阶段取
  `rerank_candidate_k` 个候选（而非直接截断到 `top_k`），再交给 reranker
  重新打分并截断到 `top_k`。
- **接入点**：全部逻辑收敛在 `hybrid_search()` 内部，对 4 个调用方
  （`app/graph/rag_graph.py` 3 处、`app/agent/tools/rag_search.py` 1 处）
  完全透明 —— 与现有 BM25 的接入模式一致，改一处、全局生效。

数据流（rerank 模式）：

```
query, query_embedding
   ├── vector_search(top_k=rerank_candidate_k)
   └── bm25_search(top_k=rerank_candidate_k)
        → reciprocal_rank_fusion(top_k=rerank_candidate_k)   # 候选集
        → reranker.rerank(query, candidates, top_k=top_k)     # 精排
        → 返回 top_k
```

## 三、模块与接口

新增 `app/retrieval/rerank/` 子包，遵循现有 `LLMProvider` 的多后端枚举风格：

```
app/retrieval/rerank/
├── __init__.py       # 导出 rerank_results() 编排函数 + get_reranker()
├── base.py           # Reranker 抽象基类 + RerankProvider 枚举
└── bge.py            # BgeReranker：本地 CrossEncoder 首发实现
```

### 抽象接口（`base.py`）

```python
class Reranker(ABC):
    @abstractmethod
    def rerank(
        self, query: str, candidates: list[dict[str, Any]], *, top_k: int
    ) -> list[dict[str, Any]]:
        """按 query 相关性对候选重排，返回 best-first 的 top_k。"""
```

- 输入/输出都是现有结果 dict（`chunk_id` / `document_id` / `content` /
  `score`）。reranker 用新的相关性分数**覆盖 `score` 字段**并重排。
- 新增 `RerankProvider` 枚举（首发 `BGE`，预留 `ARK` / `LLM`），配合
  `reranker_provider` 配置做后端分发 —— 对齐 `LLMProvider` 模式。
- `get_reranker()` 按 `reranker_provider` 返回对应实例（模块级单例缓存）。

### 首发实现 `BgeReranker`（`bge.py`）

- 封装 `sentence-transformers` 的 `CrossEncoder`，默认模型
  `BAAI/bge-reranker-v2-m3`（中文效果好、可离线）。
- **懒加载 + 单例缓存**：沿用 BM25 的模块级 `_cache` 骨架，但缓存 key 是
  **模型名**（reranker 与知识库无关，不按 kb_id 缓存）。
- 推理时对 `(query, content)` 对批量打分（`rerank_batch_size`），按分数降序
  取 `top_k`。

## 四、配置项（并入 `Settings`）

```python
class RetrievalMode(StrEnum):
    VECTOR = "vector"
    HYBRID = "hybrid"
    RERANK = "rerank"          # 新增

class RerankProvider(StrEnum):
    BGE = "bge"                # 首发
    # ARK / LLM 预留

# Settings 新增字段：
reranker_provider: RerankProvider = RerankProvider.BGE
rerank_model: str = "BAAI/bge-reranker-v2-m3"
rerank_candidate_k: int = 20      # 精排输入候选数（默认对齐 retrieval_candidate_k）
rerank_batch_size: int = 32       # CrossEncoder 推理批大小
```

## 五、错误处理与降级

沿用 BM25「失败绝不中断 Q&A」的既定风格：

- **重排失败**（模型加载失败、推理异常）→ 记 `warning` 日志（含
  `knowledge_base_id`、`exc_info`），**降级返回融合后的 `top_k`**（未重排但可用）。
- **可选依赖缺失**：`sentence-transformers` / `torch` 懒导入，`ImportError`
  时同样降级，日志提示需 `uv sync --extra rerank`。
- **候选为空**：直接返回空，不触发模型加载。

## 六、依赖与可观测性

- **依赖**：写入 `pyproject.toml` 的 `[project.optional-dependencies]` 的
  `rerank` 组（`sentence-transformers`）。非核心依赖，镜像不因此膨胀；仅启用
  rerank 模式时才需安装。
- **指标**：新增 `RAG_RERANK_DURATION` Histogram，复用 `time_stage` 上下文
  管理器观测精排耗时；融合阶段仍在 `RAG_RETRIEVAL_DURATION` 内。

## 七、测试策略

- `tests/retrieval/test_rerank.py`：
  - mock `CrossEncoder` 验证重排顺序与 `top_k` 截断；
  - 验证失败降级路径（模型异常 / `ImportError` → 返回融合结果）；
  - 空候选短路，不加载模型。
- `tests/retrieval/test_hybrid.py`：扩展验证 `rerank` 模式下的编排
  （融合取 `rerank_candidate_k` → 调用 reranker → `top_k`）。
- 模型不真实加载（CI 无 torch），全程 mock，保证测试轻量。

## 八、影响范围

- 新增：`app/retrieval/rerank/`（3 文件）、`tests/retrieval/test_rerank.py`。
- 修改：`app/retrieval/hybrid.py`（rerank 模式分支）、`app/core/config.py`
  （枚举 + 配置项）、`app/observability/metrics.py`（新指标）、
  `pyproject.toml`（可选依赖组）、`tests/retrieval/test_hybrid.py`。
- 调用方（rag_graph、rag_search）**无需改动**。
