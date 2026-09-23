"""问答模块（M3：混合检索 + 重排 + 引用溯源）。

流程：hybrid 检索（向量 + BM25，top_k）→ bge-reranker-v2-m3 重排（top_n）
→ 拼装带编号的上下文 → DeepSeek 生成回答 → 附引用列表（文件名 + PDF 页码）。
"""

from dataclasses import dataclass

from llama_index.core import VectorStoreIndex
from llama_index.core.base.llms.base import BaseLLM
from llama_index.core.schema import NodeWithScore
from llama_index.embeddings.huggingface import HuggingFaceEmbedding
from llama_index.llms.deepseek import DeepSeek

from .config import Settings
from .retrieval import hybrid_retrieve, rerank
from .store import get_vector_store

# 提示词：约束 LLM 只依据参考资料作答，并带 [n] 编号引用
_SYSTEM_PROMPT = """你是个人知识库助手。请仅根据下面提供的参考资料回答问题：
- 在相应的结论后用 [编号] 标注来源，例如"新手建议从 2%~3% 浓度开始[1]"。
- 若参考资料不足以回答，请如实说明"知识库中没有相关内容"，不要编造。
"""


@dataclass
class Citation:
    """一条引用：来源文件（含可选 PDF 页码）。"""

    index: int          # 上下文中的编号（从 1 起）
    file_name: str      # 来源文件名（展示用）
    page: str | None    # PDF 页码（非 PDF 为 None）
    source: str         # 文件绝对路径（定位用）

    @property
    def label(self) -> str:
        """引用展示文本：文件名（PDF 附加页码）。"""
        if self.page:
            return f"{self.file_name}（第 {self.page} 页）"
        return self.file_name


def build_llm(settings: Settings) -> BaseLLM:
    """构造 DeepSeek LLM 客户端（OpenAI 兼容接口）。

    Raises:
        ValueError: 当 .env 中未配置 DEEPSEEK_API_KEY 时。
    """
    if not settings.deepseek_api_key:
        raise ValueError(
            "未检测到 DEEPSEEK_API_KEY：请复制 .env.example 为 .env 并填入真实 key。"
            "（key 只应存在于 .env 中，绝不写入代码或日志）"
        )
    return DeepSeek(
        model=settings.deepseek_model,
        api_key=settings.deepseek_api_key,
        api_base=settings.deepseek_base_url,
    )


def retrieve(
    question: str,
    settings: Settings,
    top_k: int = 10,
    top_n: int = 5,
    allowed_sources: list[str] | None = None,
) -> list[NodeWithScore]:
    """完整检索管线：hybrid（向量 + BM25 各 top_k）→ rerank（top_n）。

    reranker 未配置时降级为 RRF 融合直接取前 top_n。
    """
    fused = hybrid_retrieve(question, settings, top_k, allowed_sources)
    if not fused:
        return []
    if settings.reranker_model:
        return rerank(question, fused, settings, top_n)
    return fused[:top_n]


def _build_context(nodes: list[NodeWithScore]) -> tuple[str, list[Citation]]:
    """把重排后的节点拼装为带编号的上下文，并生成对应引用列表。"""
    blocks: list[str] = []
    citations: list[Citation] = []
    for i, nws in enumerate(nodes, start=1):
        meta = nws.node.metadata
        page = meta.get("page")
        header = f"[{i}] {meta.get('file_name', '?')}"
        if page:
            header += f"（第 {page} 页）"
        blocks.append(f"{header}\n{nws.node.get_content()}")
        citations.append(
            Citation(
                index=i,
                file_name=meta.get("file_name", "?"),
                page=page,
                source=meta.get("source", ""),
            )
        )
    return "\n\n".join(blocks), citations


def run_query(
    question: str,
    settings: Settings,
    top_k: int = 10,
    top_n: int = 5,
    allowed_sources: list[str] | None = None,
) -> tuple[str, list[Citation]]:
    """单次问答：混合检索 + 重排 → DeepSeek 生成回答 + 引用列表。

    Args:
        question: 用户问题。
        settings: 全局配置。
        top_k: 混合检索每路取数（默认 10）。
        top_n: 重排后保留数量（默认 5）。
        allowed_sources: 来源白名单（可选，过滤检索范围）。

    Returns:
        (回答文本, 引用列表)。
    """
    llm = build_llm(settings)
    nodes = retrieve(question, settings, top_k, top_n, allowed_sources)
    if not nodes:
        return "知识库为空，请先执行 ink scan <路径> 摄取文档。", []

    context, citations = _build_context(nodes)
    prompt = f"{_SYSTEM_PROMPT}\n参考资料：\n{context}\n\n问题：{question}"
    response = llm.complete(prompt)
    return str(response), citations


def load_index(settings: Settings, embed_model: HuggingFaceEmbedding) -> VectorStoreIndex:
    """从 ChromaDB 加载已有索引（供纯向量检索等场景使用）。"""
    return VectorStoreIndex.from_vector_store(
        vector_store=get_vector_store(settings),
        embed_model=embed_model,
    )
