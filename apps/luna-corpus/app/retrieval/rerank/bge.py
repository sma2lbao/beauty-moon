"""Local BGE cross-encoder reranker (sentence-transformers)."""
from typing import Any

from app.core.config import get_settings
from app.retrieval.rerank.base import Reranker

settings = get_settings()

# 模块级模型缓存：model_name -> CrossEncoder 实例。
_model_cache: dict[str, Any] = {}


class BgeReranker(Reranker):
    """基于本地 CrossEncoder 模型的交叉编码器重排器。"""

    def _load_model(self) -> Any:
        """按需加载并缓存配置模型对应的 CrossEncoder。

        采用懒导入 sentence-transformers，仅在实际调用重排时才要求该依赖。
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
        """按交叉编码器相关性对候选降序取前 top_k 项。"""
        if not candidates:
            return []

        model = self._load_model()
        pairs = [(query, c["content"]) for c in candidates]
        scores = model.predict(pairs, batch_size=settings.rerank_batch_size)

        scored = [
            {**c, "score": float(score)}
            for c, score in zip(candidates, scores, strict=True)
        ]
        scored.sort(key=lambda d: d["score"], reverse=True)
        return scored[:top_k]
