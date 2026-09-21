"""混合检索与重排模块（M3 + M4 缓存优化）。

流程：
1. 向量检索（ChromaDB）与 BM25 检索（bm25s）各取 top_k；
2. 两路结果用 Reciprocal Rank Fusion（RRF）融合去重；
3. bge-reranker-v2-m3（FlagEmbedding 加载）对融合结果重排，取 top_n。

性能（M4 UI 流畅的关键）：Embedding / Reranker / BM25 索引均为
进程级 lru_cache——Streamlit 每轮对话复用已加载模型，不重复加载
（bge-reranker-v2-m3 约 2GB，重复加载会明显卡顿）。

BM25 的中文适配：默认 token_pattern 是英文单词模式（会把整段连续
中文当作一个词项），这里改为单字切分（unigram），查询词与文档
命中即可按字重合计分，是中文 BM25 的经典做法。
"""

from functools import lru_cache

from llama_index.core.schema import BaseNode, NodeWithScore, TextNode
from llama_index.embeddings.huggingface import HuggingFaceEmbedding
from llama_index.retrievers.bm25 import BM25Retriever

from .config import Settings
from .store import get_collection

# 单字切分 token 模式：适配中文（默认英文模式会把整段中文当一词项）
_ZH_TOKEN_PATTERN = r"(?u)\w"


@lru_cache(maxsize=2)
def _cached_embed_model(model_name: str) -> HuggingFaceEmbedding:
    """进程内缓存 Embedding 模型实例（首次加载后复用）。"""
    return HuggingFaceEmbedding(model_name=model_name)


@lru_cache(maxsize=2)
def _cached_reranker(model_name: str):
    """进程内缓存 FlagReranker 实例（模型约 2GB，避免每轮重复加载）。"""
    from FlagEmbedding import FlagReranker

    return FlagReranker(model_name, use_fp16=False)


@lru_cache(maxsize=8)
def _cached_bm25(
    chroma_dir: str,
    collection_name: str,
    corpus_version: int,
    allowed: tuple[str, ...] | None,
) -> BM25Retriever | None:
    """进程内缓存 BM25 索引。

    corpus_version 用 collection 的节点总数充当语料版本号：
    scan 之后再提问时（同进程内），节点数变化即重建索引。
    语料为空（无文件或全被过滤）时返回 None。
    """
    import chromadb

    collection = chromadb.PersistentClient(path=chroma_dir).get_or_create_collection(
        name=collection_name
    )
    result = collection.get(include=["documents", "metadatas"])
    nodes: list[BaseNode] = []
    allowed_set = set(allowed) if allowed is not None else None
    for node_id, text, metadata in zip(
        result["ids"], result["documents"], result["metadatas"], strict=True
    ):
        meta = metadata or {}
        if allowed_set is not None and meta.get("source") not in allowed_set:
            continue
        nodes.append(TextNode(text=text, metadata=meta, id_=node_id))
    if not nodes:
        return None
    return BM25Retriever.from_defaults(
        nodes=nodes,
        similarity_top_k=10,
        token_pattern=_ZH_TOKEN_PATTERN,
    )


def load_all_nodes(settings: Settings) -> list[BaseNode]:
    """从 ChromaDB 全量读取节点，重建为 TextNode 列表（调试 / BM25 语料用）。"""
    result = get_collection(settings).get(include=["documents", "metadatas"])
    return [
        TextNode(text=text, metadata=metadata or {}, id_=node_id)
        for node_id, text, metadata in zip(
            result["ids"], result["documents"], result["metadatas"], strict=True
        )
    ]


def _rrf_fuse(result_lists: list[list[NodeWithScore]], k: int = 60) -> list[NodeWithScore]:
    """Reciprocal Rank Fusion：按名次倒数累加融合多路检索结果。

    每路结果中排第 r 名（0 起始）的节点获得 1/(k + r + 1) 分；
    同一节点在多路命中则累加。返回按融合分降序的去重列表。
    """
    scores: dict[str, float] = {}
    kept: dict[str, NodeWithScore] = {}
    for results in result_lists:
        for rank, nws in enumerate(results):
            node_id = nws.node.node_id
            scores[node_id] = scores.get(node_id, 0.0) + 1.0 / (k + rank + 1)
            kept.setdefault(node_id, nws)
    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    return [kept[node_id] for node_id, _ in ranked]


def hybrid_retrieve(
    question: str,
    settings: Settings,
    top_k: int = 10,
    allowed_sources: list[str] | None = None,
) -> list[NodeWithScore]:
    """混合检索：向量 + BM25 各取 top_k，RRF 融合去重。

    Args:
        question: 用户问题。
        settings: 全局配置。
        top_k: 每一路检索的取数（默认 10）。
        allowed_sources: 可选的来源白名单（目录前缀 / 文件类型过滤时使用）。

    Returns:
        融合去重后的节点列表（未截断，供 rerank 使用）。
    """
    from llama_index.core import VectorStoreIndex
    from llama_index.core.vector_stores import MetadataFilters

    from .store import get_vector_store

    # ---- 向量检索（Embedding 走进程缓存）----
    if not settings.embedding_model:
        raise ValueError(
            "未配置 EMBEDDING_MODEL：请在 .env 中设置本地 Embedding 模型，"
            "例如 EMBEDDING_MODEL=BAAI/bge-m3（约 2GB）或 BAAI/bge-small-zh-v1.5（约 100MB）。"
        )
    embed_model = _cached_embed_model(settings.embedding_model)
    index = VectorStoreIndex.from_vector_store(
        vector_store=get_vector_store(settings), embed_model=embed_model
    )
    retriever_kwargs: dict = {"similarity_top_k": top_k}
    if allowed_sources is not None:
        # 过滤检索范围：只允许白名单内的 source（M4 侧边栏过滤使用）
        retriever_kwargs["filters"] = MetadataFilters.from_dict(
            {"source": {"$in": allowed_sources}}
        )
    vector_nodes = index.as_retriever(**retriever_kwargs).retrieve(question)

    # ---- BM25 检索（索引走进程缓存，按语料版本号自动失效）----
    collection = get_collection(settings)
    bm25 = _cached_bm25(
        str(settings.chroma_dir),
        settings.chroma_collection,
        collection.count(),
        tuple(allowed_sources) if allowed_sources is not None else None,
    )
    bm25_nodes: list[NodeWithScore] = bm25.retrieve(question) if bm25 is not None else []

    return _rrf_fuse([vector_nodes, bm25_nodes])


def rerank(
    question: str,
    nodes: list[NodeWithScore],
    settings: Settings,
    top_n: int = 5,
) -> list[NodeWithScore]:
    """用 bge-reranker-v2-m3 对检索结果重排，取 top_n。

    Args:
        question: 用户问题。
        nodes: 待重排的候选节点（通常来自 hybrid_retrieve）。
        settings: 全局配置（含 reranker 模型名）。
        top_n: 重排后保留数量（默认 5）。

    Returns:
        按重排分降序的前 top_n 个节点（score 更新为 reranker 分数）。
    """
    model = _cached_reranker(settings.reranker_model)
    pairs = [[question, nws.node.get_content()] for nws in nodes]
    scores = model.compute_score(pairs)
    if not isinstance(scores, list):
        scores = [scores]  # 单条候选时 FlagEmbedding 返回标量

    ranked = sorted(
        zip(nodes, scores, strict=True), key=lambda item: item[1], reverse=True
    )[:top_n]
    return [
        NodeWithScore(node=nws.node, score=float(score)) for nws, score in ranked
    ]
