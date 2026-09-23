"""Streamlit 聊天 UI（M4）。

启动：
    uv run streamlit run ink/ui.py

功能：
- 多轮对话（LLM 上下文保留最近 5 轮）
- 流式输出 token（st.write_stream）
- 回答末尾展示引用列表（文件名 + PDF 页码）
- 侧边栏按文件类型 / 目录前缀过滤检索范围
"""

from collections.abc import Generator
from pathlib import Path

import streamlit as st

from ink.config import get_settings
from ink.query import _SYSTEM_PROMPT, Citation, _build_context, build_llm, retrieve
from ink.store import get_collection

# LLM 上下文保留的最近对话轮数
CHAT_HISTORY_ROUNDS = 5


@st.cache_data(ttl=30)
def _list_files(chroma_dir: str, collection_name: str) -> list[dict[str, str]]:
    """列出知识库中已入库的文件（source + file_name），供侧边栏过滤。

    30 秒缓存：scan 之后最多延迟 30 秒反映到侧边栏。
    """
    settings = get_settings()
    collection = get_collection(settings)
    result = collection.get(include=["metadatas"])
    seen: dict[str, str] = {}
    for meta in result.get("metadatas") or []:
        if meta and "source" in meta:
            seen[meta["source"]] = meta.get("file_name", "?")
    return [{"source": s, "file_name": n} for s, n in seen.items()]


def _compute_allowed_sources(
    files: list[dict[str, str]], types: list[str], dir_prefixes: list[str]
) -> list[str] | None:
    """按侧边栏选择计算来源白名单。

    全部文件都命中时返回 None（不过滤，等价全库检索）。
    """
    allowed = [
        f["source"]
        for f in files
        if Path(f["source"]).suffix in set(types)
        and any(Path(f["source"]).is_relative_to(p) for p in map(Path, dir_prefixes))
    ]
    return None if len(allowed) == len(files) and files else (allowed or None)


def _render_citations(citations: list[Citation]) -> None:
    """渲染回答末尾的引用列表（可折叠）。"""
    with st.expander(f"📎 来源（{len(citations)}）"):
        for c in citations:
            st.markdown(f"- [{c.index}] {c.label}")


def _build_prompt(
    history: list[dict], context: str, question: str
) -> str:
    """组装 LLM 提示词：system + 最近 5 轮对话 + 参考资料 + 当前问题。"""
    # 每轮含 user / assistant 两条，取最近 5 轮
    recent = history[-(2 * CHAT_HISTORY_ROUNDS) :]
    lines = [
        f"{'用户' if m['role'] == 'user' else '助手'}：{m['content']}" for m in recent
    ]
    parts = [_SYSTEM_PROMPT]
    if lines:
        parts.append(
            "以下是最近的对话历史（仅供理解上下文，回答仍以本次参考资料为准）：\n"
            + "\n".join(lines)
        )
    parts.append(f"参考资料：\n{context}")
    parts.append(f"问题：{question}")
    return "\n\n".join(parts)


def _stream_deltas(llm, prompt: str) -> Generator[str]:
    """把 LlamaIndex 的流式响应转换为 token 增量生成器（供 st.write_stream）。"""
    for resp in llm.stream_complete(prompt):
        if resp.delta:
            yield resp.delta


def main() -> None:
    """Streamlit 应用入口。"""
    st.set_page_config(page_title="ink", page_icon="🖌️", layout="wide")
    st.title("🖌️ ink 个人知识库")
    st.caption("本地 RAG 问答：混合检索（向量 + BM25）→ bge-reranker 重排 → DeepSeek 生成")

    settings = get_settings()
    if not settings.embedding_model or not settings.deepseek_api_key:
        st.warning(
            "尚未完成配置：请在 apps/ink/.env 中设置 "
            "`DEEPSEEK_API_KEY` 与 `EMBEDDING_MODEL`（参考 .env.example），"
            "并先执行 `uv run python -m ink scan ./docs` 摄取文档。"
        )

    # ---- 侧边栏：检索范围过滤 ----
    files = _list_files(str(settings.chroma_dir), settings.chroma_collection)
    with st.sidebar:
        st.header("检索范围")
        if not files:
            st.info("知识库为空：请先执行 ink scan <路径> 摄取文档。")
        all_types = sorted({Path(f["source"]).suffix for f in files})
        all_dirs = sorted({str(Path(f["source"]).parent) for f in files})
        sel_types = st.multiselect("文件类型", all_types, default=all_types)
        sel_dirs = st.multiselect("目录（前缀匹配）", all_dirs, default=all_dirs)
        allowed_sources = _compute_allowed_sources(files, sel_types, sel_dirs)
        in_scope = len(allowed_sources) if allowed_sources else len(files)
        st.caption(f"范围内：{in_scope}/{len(files)} 个文件")
        st.divider()
        st.caption(
            f"Embedding：{settings.embedding_model or '（未配置）'}\n\n"
            f"Reranker：{settings.reranker_model or '（未配置，跳过重排）'}"
        )
        if st.button("🗑️ 清空对话", use_container_width=True):
            st.session_state.history = []
            st.rerun()

    # ---- 会话状态初始化 ----
    if "history" not in st.session_state:
        st.session_state.history = []  # list[dict(role, content, citations?)]

    # ---- 渲染历史消息 ----
    for msg in st.session_state.history:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
            if msg.get("citations"):
                _render_citations(msg["citations"])

    # ---- 输入与回答 ----
    question = st.chat_input("问点什么，例如：视黄醇孕期还能用吗？")
    if not question:
        return

    st.session_state.history.append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.markdown(question)

    with st.chat_message("assistant"):
        with st.spinner("检索知识库…（首次运行需下载 / 加载模型，请耐心等待）"):
            nodes = retrieve(question, settings, allowed_sources=allowed_sources)
        if not nodes:
            answer = "知识库为空或当前过滤条件下无命中，请先执行 ink scan 摄取文档。"
            st.markdown(answer)
            citations: list[Citation] = []
        else:
            context, citations = _build_context(nodes)
            prompt = _build_prompt(st.session_state.history[:-1], context, question)
            llm = build_llm(settings)
            # 流式输出：token 逐段写入页面，无整体阻塞
            answer = st.write_stream(_stream_deltas(llm, prompt))
            _render_citations(citations)

    st.session_state.history.append(
        {"role": "assistant", "content": answer, "citations": citations}
    )


if __name__ == "__main__":
    main()
