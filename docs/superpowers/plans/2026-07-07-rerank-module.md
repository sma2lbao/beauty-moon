# 重排（Rerank）模块 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 luna-corpus 的混合检索之后增加透明的交叉编码器精排（rerank）阶段，作为 `retrieval_mode` 的第三档。

**Architecture:** 新增 `app/retrieval/rerank/` 子包（抽象 `Reranker` 接口 + `RerankProvider` 枚举 + 本地 BGE 首发实现），在 `hybrid_search()` 内部按 `retrieval_mode=rerank` 分支调用精排，对所有调用方透明。失败降级到融合结果，风格对齐现有 BM25。

**Tech Stack:** Python 3.11+、FastAPI、sentence-transformers（CrossEncoder，可选依赖）、prometheus-client、pytest。

## Global Constraints

- 目标应用目录：`apps/luna-corpus`；所有路径相对该目录。
- 包管理器统一 `npm`；测试通过 `npm exec nx test luna-corpus` 或直接 `pytest`（在 `apps/luna-corpus` 下）运行。
- 重排失败**绝不中断 Q&A**：记 `warning` 日志（含 `knowledge_base_id`、`exc_info`）并降级返回融合后的 `top_k`。
- `sentence-transformers` 为**可选依赖**（`[project.optional-dependencies].rerank`），代码中懒导入，缺失时降级。
- 结果 dict 契约固定为 `{"chunk_id", "document_id", "content", "score"}`；reranker 用新相关性分数覆盖 `score`。
- 中文注释与文档；遵循现有代码风格（模块级 `settings = get_settings()`、`get_logger` 命名空间）。

---

### Task 1: 配置项 —— RerankProvider 枚举与 rerank 设置

**Files:**
- Modify: `apps/luna-corpus/app/core/config.py`
- Test: `apps/luna-corpus/tests/core/test_config_rerank.py`

**Interfaces:**
- Consumes: 现有 `RetrievalMode` StrEnum、`Settings(BaseSettings)`。
- Produces:
  - `RetrievalMode.RERANK = "rerank"`
  - `class RerankProvider(StrEnum): BGE = "bge"`
  - `Settings.reranker_provider: RerankProvider`（默认 `BGE`）
  - `Settings.rerank_model: str`（默认 `"BAAI/bge-reranker-v2-m3"`）
  - `Settings.rerank_candidate_k: int`（默认 `20`）
  - `Settings.rerank_batch_size: int`（默认 `32`）

- [ ] **Step 1: 写失败测试**

Create `apps/luna-corpus/tests/core/test_config_rerank.py`:

```python
"""Tests for rerank-related settings."""
from app.core.config import RerankProvider, RetrievalMode, Settings


def test_retrieval_mode_has_rerank():
    assert RetrievalMode.RERANK == "rerank"


def test_rerank_provider_default_is_bge():
    settings = Settings()
    assert settings.reranker_provider == RerankProvider.BGE


def test_rerank_defaults():
    settings = Settings()
    assert settings.rerank_model == "BAAI/bge-reranker-v2-m3"
    assert settings.rerank_candidate_k == 20
    assert settings.rerank_batch_size == 32
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd apps/luna-corpus && python -m pytest tests/core/test_config_rerank.py -v`
Expected: FAIL（`ImportError: cannot import name 'RerankProvider'`）

- [ ] **Step 3: 实现配置**

在 `app/core/config.py` 的 `RetrievalMode` 中新增成员：

```python
class RetrievalMode(StrEnum):
    """Retrieval strategies."""

    VECTOR = "vector"
    HYBRID = "hybrid"
    RERANK = "rerank"
```

在 `RetrievalMode` 类之后新增枚举：

```python
class RerankProvider(StrEnum):
    """Available rerank backends."""

    BGE = "bge"
```

在 `Settings` 的 RAG 区块（`bm25_cache_ttl_seconds` 之后）新增：

```python
    # Rerank
    reranker_provider: RerankProvider = Field(
        default=RerankProvider.BGE,
        description="重排后端：bge 本地交叉编码器",
    )
    rerank_model: str = Field(
        default="BAAI/bge-reranker-v2-m3",
        description="交叉编码器模型名（sentence-transformers CrossEncoder）",
    )
    rerank_candidate_k: int = Field(
        default=20, description="rerank 模式下送入精排的候选数量"
    )
    rerank_batch_size: int = Field(
        default=32, description="CrossEncoder 推理批大小"
    )
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd apps/luna-corpus && python -m pytest tests/core/test_config_rerank.py -v`
Expected: PASS（3 passed）

- [ ] **Step 5: 提交**

```bash
git add apps/luna-corpus/app/core/config.py apps/luna-corpus/tests/core/test_config_rerank.py
git commit -m "feat(corpus): add rerank config (RerankProvider, rerank settings)"
```

---

### Task 2: 精排指标 RAG_RERANK_DURATION

**Files:**
- Modify: `apps/luna-corpus/app/observability/metrics.py`
- Test: `apps/luna-corpus/tests/observability/test_metrics_rerank.py`

**Interfaces:**
- Consumes: 现有 `time_stage` 上下文管理器、`Histogram`。
- Produces: `RAG_RERANK_DURATION: Histogram`（无标签，指标名 `rag_rerank_duration_seconds`）。

- [ ] **Step 1: 写失败测试**

Create `apps/luna-corpus/tests/observability/test_metrics_rerank.py`:

```python
"""Tests for the rerank duration metric."""
from app.observability.metrics import RAG_RERANK_DURATION, time_stage


def test_rerank_duration_metric_records():
    before = RAG_RERANK_DURATION._sum.get()
    with time_stage(RAG_RERANK_DURATION):
        pass
    after = RAG_RERANK_DURATION._sum.get()
    assert after >= before
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd apps/luna-corpus && python -m pytest tests/observability/test_metrics_rerank.py -v`
Expected: FAIL（`ImportError: cannot import name 'RAG_RERANK_DURATION'`）

- [ ] **Step 3: 实现指标**

在 `app/observability/metrics.py` 的 `RAG_RETRIEVAL_DURATION` 定义之后新增：

```python
RAG_RERANK_DURATION = Histogram(
    "rag_rerank_duration_seconds",
    "Rerank (cross-encoder) latency in seconds.",
)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd apps/luna-corpus && python -m pytest tests/observability/test_metrics_rerank.py -v`
Expected: PASS（1 passed）

- [ ] **Step 5: 提交**

```bash
git add apps/luna-corpus/app/observability/metrics.py apps/luna-corpus/tests/observability/test_metrics_rerank.py
git commit -m "feat(corpus): add rag_rerank_duration_seconds metric"
```

---

### Task 3: Reranker 抽象接口与后端分发

**Files:**
- Create: `apps/luna-corpus/app/retrieval/rerank/__init__.py`
- Create: `apps/luna-corpus/app/retrieval/rerank/base.py`
- Test: `apps/luna-corpus/tests/retrieval/test_rerank_base.py`

**Interfaces:**
- Consumes: `app.core.config`（`get_settings`、`RerankProvider`）。
- Produces:
  - `class Reranker(ABC)`，抽象方法 `rerank(self, query: str, candidates: list[dict[str, Any]], *, top_k: int) -> list[dict[str, Any]]`
  - `get_reranker() -> Reranker`：按 `settings.reranker_provider` 返回单例；未知 provider 抛 `ValueError`。
  - `reset_reranker_cache() -> None`：测试辅助，清空单例缓存。

- [ ] **Step 1: 写失败测试**

Create `apps/luna-corpus/tests/retrieval/test_rerank_base.py`:

```python
"""Tests for the reranker abstraction and backend dispatch."""
import pytest

from app.retrieval.rerank import base


class _FakeReranker(base.Reranker):
    def rerank(self, query, candidates, *, top_k):
        return candidates[:top_k]


def test_reranker_is_abstract():
    with pytest.raises(TypeError):
        base.Reranker()  # abstract, cannot instantiate


def test_get_reranker_returns_singleton(monkeypatch):
    base.reset_reranker_cache()
    monkeypatch.setattr(base, "_build_reranker", lambda: _FakeReranker())
    first = base.get_reranker()
    second = base.get_reranker()
    assert first is second


def test_get_reranker_unknown_provider_raises(monkeypatch):
    base.reset_reranker_cache()
    monkeypatch.setattr(base.settings, "reranker_provider", "nope")
    with pytest.raises(ValueError):
        base._build_reranker()
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd apps/luna-corpus && python -m pytest tests/retrieval/test_rerank_base.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'app.retrieval.rerank'`）

- [ ] **Step 3: 实现抽象层**

Create `apps/luna-corpus/app/retrieval/rerank/__init__.py`:

```python
"""Rerank stage: cross-encoder precision reranking over fused candidates.

Enabled via ``retrieval_mode=rerank``. Backend selected by
``reranker_provider`` (currently ``bge``, local CrossEncoder). Reranking must
never break Q&A: failures degrade to the fused results (see ``rerank_results``).
"""
from app.retrieval.rerank.base import Reranker, get_reranker, reset_reranker_cache

__all__ = ["Reranker", "get_reranker", "reset_reranker_cache"]
```

Create `apps/luna-corpus/app/retrieval/rerank/base.py`:

```python
"""Reranker abstraction and backend dispatch."""
from abc import ABC, abstractmethod
from typing import Any

from app.core.config import RerankProvider, get_settings

settings = get_settings()


class Reranker(ABC):
    """Reorders retrieval candidates by query relevance."""

    @abstractmethod
    def rerank(
        self, query: str, candidates: list[dict[str, Any]], *, top_k: int
    ) -> list[dict[str, Any]]:
        """Return the best-first ``top_k`` candidates, ``score`` overwritten
        with the reranker's relevance score."""


# Module-level singleton cache (reranker is KB-independent).
_instance: Reranker | None = None


def _build_reranker() -> Reranker:
    """Construct the reranker for the configured provider."""
    if settings.reranker_provider == RerankProvider.BGE:
        from app.retrieval.rerank.bge import BgeReranker

        return BgeReranker()
    raise ValueError(f"Unknown reranker provider: {settings.reranker_provider}")


def get_reranker() -> Reranker:
    """Return the cached reranker singleton, building it on first use."""
    global _instance
    if _instance is None:
        _instance = _build_reranker()
    return _instance


def reset_reranker_cache() -> None:
    """Drop the cached reranker (test helper)."""
    global _instance
    _instance = None
```

> 注：`test_get_reranker_returns_singleton` 通过 monkeypatch `_build_reranker` 避免真实加载 BGE 模型。

- [ ] **Step 4: 运行测试确认通过**

Run: `cd apps/luna-corpus && python -m pytest tests/retrieval/test_rerank_base.py -v`
Expected: PASS（3 passed）

- [ ] **Step 5: 提交**

```bash
git add apps/luna-corpus/app/retrieval/rerank/__init__.py apps/luna-corpus/app/retrieval/rerank/base.py apps/luna-corpus/tests/retrieval/test_rerank_base.py
git commit -m "feat(corpus): add Reranker abstraction and backend dispatch"
```

---

### Task 4: BgeReranker 本地交叉编码器实现

**Files:**
- Create: `apps/luna-corpus/app/retrieval/rerank/bge.py`
- Test: `apps/luna-corpus/tests/retrieval/test_rerank_bge.py`

**Interfaces:**
- Consumes: `Reranker`（Task 3）、`settings`（`rerank_model`、`rerank_batch_size`）。
- Produces: `class BgeReranker(Reranker)`，懒加载 `sentence_transformers.CrossEncoder`，模块级模型缓存 `_model_cache: dict[str, Any]`。`rerank()` 对空候选返回 `[]` 且不加载模型；否则对 `(query, content)` 批量 `predict`，按分覆盖 `score` 降序取 `top_k`。

- [ ] **Step 1: 写失败测试**

Create `apps/luna-corpus/tests/retrieval/test_rerank_bge.py`:

```python
"""Tests for the local BGE cross-encoder reranker."""
from app.retrieval.rerank import bge


class _FakeModel:
    """Stand-in for CrossEncoder: score = length of content string."""

    def __init__(self):
        self.predict_calls = []

    def predict(self, pairs, batch_size=32):
        self.predict_calls.append((pairs, batch_size))
        return [float(len(content)) for _query, content in pairs]


def _cand(chunk_id, content):
    return {
        "chunk_id": chunk_id,
        "document_id": f"doc-{chunk_id}",
        "content": content,
        "score": 0.0,
    }


def test_rerank_orders_by_model_score_and_truncates(monkeypatch):
    reranker = bge.BgeReranker()
    monkeypatch.setattr(reranker, "_load_model", lambda: _FakeModel())

    candidates = [_cand("a", "xx"), _cand("b", "xxxxxx"), _cand("c", "xxxx")]
    result = reranker.rerank("q", candidates, top_k=2)

    # Longer content -> higher fake score -> "b" then "c".
    assert [r["chunk_id"] for r in result] == ["b", "c"]
    assert result[0]["score"] == 6.0


def test_rerank_empty_candidates_skips_model(monkeypatch):
    reranker = bge.BgeReranker()

    def _boom():
        raise AssertionError("model must not load for empty candidates")

    monkeypatch.setattr(reranker, "_load_model", _boom)
    assert reranker.rerank("q", [], top_k=5) == []


def test_rerank_preserves_result_contract(monkeypatch):
    reranker = bge.BgeReranker()
    monkeypatch.setattr(reranker, "_load_model", lambda: _FakeModel())

    result = reranker.rerank("q", [_cand("a", "xx")], top_k=5)
    assert set(result[0].keys()) == {"chunk_id", "document_id", "content", "score"}
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd apps/luna-corpus && python -m pytest tests/retrieval/test_rerank_bge.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'app.retrieval.rerank.bge'`）

- [ ] **Step 3: 实现 BgeReranker**

Create `apps/luna-corpus/app/retrieval/rerank/bge.py`:

```python
"""Local BGE cross-encoder reranker (sentence-transformers)."""
from typing import Any

from app.core.config import get_settings
from app.retrieval.rerank.base import Reranker

settings = get_settings()

# Module-level model cache: model_name -> CrossEncoder instance.
_model_cache: dict[str, Any] = {}


class BgeReranker(Reranker):
    """Cross-encoder reranker backed by a local CrossEncoder model."""

    def _load_model(self) -> Any:
        """Lazily load and cache the CrossEncoder for the configured model.

        Imports sentence-transformers lazily so the dependency is only
        required when rerank is actually used.
        """
        name = settings.rerank_model
        model = _model_cache.get(name)
        if model is None:
            from sentence_transformers import CrossEncoder

            model = CrossEncoder(name)
            _model_cache[name] = model
        return model

    def rerank(
        self, query: str, candidates: list[dict[str, Any]], *, top_k: int
    ) -> list[dict[str, Any]]:
        """Rerank candidates by cross-encoder relevance, best-first top_k."""
        if not candidates:
            return []

        model = self._load_model()
        pairs = [(query, c["content"]) for c in candidates]
        scores = model.predict(pairs, batch_size=settings.rerank_batch_size)

        scored = [
            {**c, "score": float(score)}
            for c, score in zip(candidates, scores)
        ]
        scored.sort(key=lambda d: d["score"], reverse=True)
        return scored[:top_k]
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd apps/luna-corpus && python -m pytest tests/retrieval/test_rerank_bge.py -v`
Expected: PASS（3 passed）

- [ ] **Step 5: 提交**

```bash
git add apps/luna-corpus/app/retrieval/rerank/bge.py apps/luna-corpus/tests/retrieval/test_rerank_bge.py
git commit -m "feat(corpus): add BgeReranker (local cross-encoder)"
```

---

### Task 5: rerank_results 编排 + 失败降级

**Files:**
- Modify: `apps/luna-corpus/app/retrieval/rerank/base.py`
- Modify: `apps/luna-corpus/app/retrieval/rerank/__init__.py`
- Test: `apps/luna-corpus/tests/retrieval/test_rerank_orchestration.py`

**Interfaces:**
- Consumes: `get_reranker`（Task 3）、`RAG_RERANK_DURATION` + `time_stage`（Task 2）、`get_logger`。
- Produces: `rerank_results(query: str, candidates: list[dict[str, Any]], *, top_k: int, knowledge_base_id: str) -> list[dict[str, Any]]`：调用 reranker 精排；任何异常（含 `ImportError`）记 warning 并降级返回 `candidates[:top_k]`。

- [ ] **Step 1: 写失败测试**

Create `apps/luna-corpus/tests/retrieval/test_rerank_orchestration.py`:

```python
"""Tests for the rerank_results orchestration + degradation."""
from app.retrieval.rerank import base


class _StubReranker:
    def rerank(self, query, candidates, *, top_k):
        # Reverse order to prove reranking happened.
        return list(reversed(candidates))[:top_k]


def _cand(chunk_id):
    return {
        "chunk_id": chunk_id,
        "document_id": f"doc-{chunk_id}",
        "content": f"content {chunk_id}",
        "score": 0.5,
    }


def test_rerank_results_uses_reranker(monkeypatch):
    monkeypatch.setattr(base, "get_reranker", lambda: _StubReranker())
    candidates = [_cand("a"), _cand("b"), _cand("c")]

    result = base.rerank_results(
        "q", candidates, top_k=2, knowledge_base_id="kb-1"
    )

    assert [r["chunk_id"] for r in result] == ["c", "b"]


def test_rerank_results_degrades_on_error(monkeypatch):
    def _boom():
        raise RuntimeError("model exploded")

    monkeypatch.setattr(base, "get_reranker", _boom)
    candidates = [_cand("a"), _cand("b"), _cand("c")]

    result = base.rerank_results(
        "q", candidates, top_k=2, knowledge_base_id="kb-1"
    )

    # Degrades to fused order, sliced to top_k.
    assert [r["chunk_id"] for r in result] == ["a", "b"]


def test_rerank_results_degrades_on_import_error(monkeypatch):
    def _boom():
        raise ImportError("no sentence-transformers")

    monkeypatch.setattr(base, "get_reranker", _boom)
    candidates = [_cand("a"), _cand("b")]

    result = base.rerank_results(
        "q", candidates, top_k=5, knowledge_base_id="kb-1"
    )

    assert [r["chunk_id"] for r in result] == ["a", "b"]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd apps/luna-corpus && python -m pytest tests/retrieval/test_rerank_orchestration.py -v`
Expected: FAIL（`AttributeError: module 'app.retrieval.rerank.base' has no attribute 'rerank_results'`）

- [ ] **Step 3: 实现编排函数**

在 `app/retrieval/rerank/base.py` 顶部补充导入：

```python
from app.observability.logging import get_logger
from app.observability.metrics import RAG_RERANK_DURATION, time_stage
```

并在文件末尾（`reset_reranker_cache` 之后）新增：

```python
logger = get_logger("luna.retrieval.rerank")


def rerank_results(
    query: str,
    candidates: list[dict[str, Any]],
    *,
    top_k: int,
    knowledge_base_id: str,
) -> list[dict[str, Any]]:
    """Rerank fused candidates, degrading to fused order on any failure.

    Reranking must never break Q&A: model load / inference / missing-dependency
    errors are logged and we return ``candidates[:top_k]`` unchanged.
    """
    if not candidates:
        return []
    try:
        with time_stage(RAG_RERANK_DURATION):
            return get_reranker().rerank(query, candidates, top_k=top_k)
    except Exception:  # Rerank must never break Q&A — degrade to fused order.
        logger.warning(
            "rerank_failed_degrading_to_fused",
            knowledge_base_id=knowledge_base_id,
            exc_info=True,
        )
        return candidates[:top_k]
```

在 `app/retrieval/rerank/__init__.py` 中导出：

```python
"""Rerank stage: cross-encoder precision reranking over fused candidates.

Enabled via ``retrieval_mode=rerank``. Backend selected by
``reranker_provider`` (currently ``bge``, local CrossEncoder). Reranking must
never break Q&A: failures degrade to the fused results (see ``rerank_results``).
"""
from app.retrieval.rerank.base import (
    Reranker,
    get_reranker,
    rerank_results,
    reset_reranker_cache,
)

__all__ = ["Reranker", "get_reranker", "rerank_results", "reset_reranker_cache"]
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd apps/luna-corpus && python -m pytest tests/retrieval/test_rerank_orchestration.py -v`
Expected: PASS（3 passed）

- [ ] **Step 5: 提交**

```bash
git add apps/luna-corpus/app/retrieval/rerank/base.py apps/luna-corpus/app/retrieval/rerank/__init__.py apps/luna-corpus/tests/retrieval/test_rerank_orchestration.py
git commit -m "feat(corpus): add rerank_results orchestration with degradation"
```

---

### Task 6: 接入 hybrid_search（rerank 模式分支）

**Files:**
- Modify: `apps/luna-corpus/app/retrieval/hybrid.py`
- Modify: `apps/luna-corpus/tests/retrieval/test_hybrid.py`

**Interfaces:**
- Consumes: `rerank_results`（Task 5）、`settings.rerank_candidate_k`、`RetrievalMode.RERANK`。
- Produces: `hybrid_search()` 在 `rerank` 模式下：向量+BM25 各取 `rerank_candidate_k`，RRF 融合到 `rerank_candidate_k`，再 `rerank_results(... top_k=top_k)`。`vector`/`hybrid` 模式行为不变。

- [ ] **Step 1: 写失败测试**

在 `apps/luna-corpus/tests/retrieval/test_hybrid.py` 顶部导入补充 rerank 模块，并扩展 `_configure` 后追加测试。先在 import 区新增：

```python
from app.retrieval.rerank import base as rerank_base
```

在文件末尾追加：

```python
def test_rerank_mode_reranks_fused_candidates(monkeypatch):
    _configure(
        monkeypatch,
        RetrievalMode.RERANK,
        vector_results=[_vdoc("a"), _vdoc("b")],
        bm25_results=[_bm25hit("c")],
    )

    # Stub reranker: pick "c" to the top to prove rerank ran after fusion.
    class _StubReranker:
        def rerank(self, query, candidates, *, top_k):
            ordered = sorted(candidates, key=lambda d: d["chunk_id"] != "c")
            return ordered[:top_k]

    monkeypatch.setattr(rerank_base, "get_reranker", lambda: _StubReranker())

    results = hybrid.hybrid_search(
        "q", [0.1, 0.2], top_k=2, knowledge_base_id="kb-1"
    )

    assert results[0]["chunk_id"] == "c"
    assert len(results) == 2


def test_rerank_mode_overfetches_candidate_k(monkeypatch):
    captured = _configure(
        monkeypatch,
        RetrievalMode.RERANK,
        vector_results=[_vdoc("a")],
        bm25_results=[_bm25hit("a")],
    )
    monkeypatch.setattr(
        rerank_base, "get_reranker",
        lambda: type("R", (), {"rerank": lambda self, q, c, *, top_k: c[:top_k]})(),
    )

    hybrid.hybrid_search("q", [0.1, 0.2], top_k=5, knowledge_base_id="kb-1")

    assert captured["vector_top_k"] == Settings().rerank_candidate_k


def test_rerank_mode_degrades_when_reranker_raises(monkeypatch):
    _configure(
        monkeypatch,
        RetrievalMode.RERANK,
        vector_results=[_vdoc("a"), _vdoc("b")],
        bm25_results=[_bm25hit("c")],
    )

    def _boom():
        raise RuntimeError("reranker down")

    monkeypatch.setattr(rerank_base, "get_reranker", _boom)

    results = hybrid.hybrid_search(
        "q", [0.1, 0.2], top_k=5, knowledge_base_id="kb-1"
    )

    # Degrades to fused results; "a" (both paths) still ranks first.
    assert results[0]["chunk_id"] == "a"
    assert {r["chunk_id"] for r in results} == {"a", "b", "c"}
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd apps/luna-corpus && python -m pytest tests/retrieval/test_hybrid.py -k rerank -v`
Expected: FAIL（rerank 模式当前走 `!= HYBRID` 分支，直接返回向量结果，断言不满足）

- [ ] **Step 3: 修改 hybrid_search**

在 `app/retrieval/hybrid.py` 顶部导入区新增：

```python
from app.retrieval.rerank import rerank_results
```

将 `hybrid_search` 函数体替换为（保留原 docstring 首段，补充 rerank 说明）：

```python
def hybrid_search(
    query: str,
    query_embedding: list[float],
    *,
    top_k: int,
    knowledge_base_id: str,
) -> list[dict[str, Any]]:
    """Retrieve chunks for a query, dispatching on ``settings.retrieval_mode``.

    ``vector`` mode is plain vector search. ``hybrid`` runs vector + BM25 (each
    up to ``retrieval_candidate_k``) fused with RRF to ``top_k``. ``rerank``
    fuses to ``rerank_candidate_k`` candidates then cross-encoder reranks to
    ``top_k``. BM25 failure degrades to vector-only; rerank failure degrades to
    fused order. A vector failure propagates.
    """
    mode = settings.retrieval_mode
    is_fused = mode in (RetrievalMode.HYBRID, RetrievalMode.RERANK)
    candidate_k = (
        settings.rerank_candidate_k
        if mode == RetrievalMode.RERANK
        else settings.retrieval_candidate_k
    )
    # rerank fuses to candidate_k first; hybrid fuses straight to top_k.
    fuse_top_k = candidate_k if mode == RetrievalMode.RERANK else top_k

    with time_stage(RAG_RETRIEVAL_DURATION):
        vector_results = search_vectorstore(
            query_embedding=query_embedding,
            top_k=candidate_k if is_fused else top_k,
            knowledge_base_id=knowledge_base_id,
        )

        if not is_fused:
            return vector_results

        try:
            keyword_results = _bm25_results(
                query, knowledge_base_id, candidate_k
            )
        except Exception:  # BM25 must never break Q&A — degrade to vector-only.
            logger.warning(
                "bm25_search_failed_degrading_to_vector",
                knowledge_base_id=knowledge_base_id,
                exc_info=True,
            )
            return vector_results[:top_k]

        fused = reciprocal_rank_fusion(
            [vector_results, keyword_results],
            k=settings.rrf_k,
            top_k=fuse_top_k,
        )

        if mode == RetrievalMode.RERANK:
            return rerank_results(
                query,
                fused,
                top_k=top_k,
                knowledge_base_id=knowledge_base_id,
            )
        return fused
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd apps/luna-corpus && python -m pytest tests/retrieval/test_hybrid.py -v`
Expected: PASS（原 7 项 + 新 3 项 = 10 passed）

- [ ] **Step 5: 提交**

```bash
git add apps/luna-corpus/app/retrieval/hybrid.py apps/luna-corpus/tests/retrieval/test_hybrid.py
git commit -m "feat(corpus): route rerank mode through hybrid_search"
```

---

### Task 7: 可选依赖组 + 文档

**Files:**
- Modify: `apps/luna-corpus/pyproject.toml`
- Modify: `apps/luna-corpus/app/retrieval/__init__.py`

**Interfaces:**
- Consumes: 无新增运行时接口。
- Produces: `[project.optional-dependencies].rerank = ["sentence-transformers>=3.0"]`；更新 retrieval 包 docstring 说明 rerank 模式。

- [ ] **Step 1: 添加可选依赖组**

在 `apps/luna-corpus/pyproject.toml` 的 `dependencies` 数组结束（`]`）之后、`[project]` 表范围内新增：

```toml
[project.optional-dependencies]
rerank = [
    # Local cross-encoder reranking (bge-reranker); pulls in torch.
    "sentence-transformers>=3.0",
]
```

- [ ] **Step 2: 验证 TOML 可解析**

Run: `cd apps/luna-corpus && python -c "import tomllib; tomllib.load(open('pyproject.toml','rb')); print('ok')"`
Expected: 输出 `ok`

- [ ] **Step 3: 更新 retrieval 包文档**

将 `apps/luna-corpus/app/retrieval/__init__.py` 内容替换为：

```python
"""Retrieval orchestration: vector, BM25, fusion, and rerank.

Set ``retrieval_mode`` in settings to ``vector`` (vector-only, legacy
behavior), ``hybrid`` (vector + BM25 fused with RRF, default), or ``rerank``
(hybrid fusion to ``rerank_candidate_k`` candidates, then a cross-encoder
reranks to ``top_k``). The BM25 index is per knowledge base, lazily built and
cached with active invalidation on chunk write/delete plus a
``bm25_cache_ttl_seconds`` fallback. Rerank uses a KB-independent model
singleton; ``sentence-transformers`` is an optional dependency (extra
``rerank``) and rerank failures degrade to the fused results.
"""
```

- [ ] **Step 4: 运行检索测试套件确认无回归**

Run: `cd apps/luna-corpus && python -m pytest tests/retrieval/ -v`
Expected: PASS（全部通过）

- [ ] **Step 5: 提交**

```bash
git add apps/luna-corpus/pyproject.toml apps/luna-corpus/app/retrieval/__init__.py
git commit -m "feat(corpus): add rerank optional-dependency group and docs"
```

---

### Task 8: 全量回归与收尾

**Files:**
- 无新增；验证全套测试。

- [ ] **Step 1: 运行 luna-corpus 全量测试**

Run: `cd apps/luna-corpus && python -m pytest -q`
Expected: 全部通过，无新增失败。

- [ ] **Step 2: 运行 lint（若配置）**

Run: `npm exec nx lint luna-corpus`
Expected: PASS（或与主分支基线一致）。若 nx target 不存在，改用 `cd apps/luna-corpus && ruff check app tests`。

- [ ] **Step 3: 确认无遗漏提交**

Run: `git status --short`
Expected: 干净（所有变更已在前序任务提交）。
```
```

## 覆盖校验

- spec §二/§六（三档模式 + 指标）→ Task 6、Task 2
- spec §三（接口/子包/BGE 单例）→ Task 3、Task 4
- spec §四（配置项）→ Task 1
- spec §五（失败降级）→ Task 5、Task 6
- spec §六（可选依赖 + 指标）→ Task 7、Task 2
- spec §七（测试）→ 各 Task 的 TDD 步骤
- spec §八（影响范围/调用方不改）→ Task 6（透明接入，rag_graph/rag_search 未列入修改）
