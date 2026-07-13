"""File-backed default templates for the RAG Q&A prompt.

Plain-Python constants (not YAML) — the project keeps dependencies minimal
and has no yaml package. These are the fail-safe layer: always available
even when the DB has no rows.
"""

RAG_QA_PROMPT_KEY = "rag_qa"

_ZH_TEMPLATE = """你是一个基于文档的问答助手。请根据提供的上下文信息回答问题。

{body}

请基于上述信息给出回答。如果上下文中没有相关信息，请说明无法从提供的文档中找到答案。"""

_EN_TEMPLATE = """You are a document-based Q&A assistant. Please answer questions based on the provided context.

{body}

Please provide your answer based on the above information. If the relevant information is not found in the context, please indicate that you cannot find an answer from the provided documents."""

DEFAULT_TEMPLATES: dict[tuple[str, str], dict] = {
    (RAG_QA_PROMPT_KEY, "zh"): {
        "version_label": "file-default-zh",
        "template_text": _ZH_TEMPLATE,
    },
    (RAG_QA_PROMPT_KEY, "en"): {
        "version_label": "file-default-en",
        "template_text": _EN_TEMPLATE,
    },
}


def default_version_id(prompt_key: str, lang: str) -> str:
    """Synthetic stable id for a file-default version."""
    return f"file::{prompt_key}::{lang}"


def render_rag_body(
    question: str,
    context: str,
    conversation_history: str = "",
    conversation_summary: str | None = None,
) -> str:
    """Assemble the [sections] body shared by all rag_qa templates."""
    parts = []
    if conversation_summary:
        parts.append(f"[Prior Conversation Summary]\n{conversation_summary}\n")
    if conversation_history:
        parts.append(f"[Current Conversation]\n{conversation_history}\n")
    if context:
        parts.append(f"[Relevant Documents]\n{context}\n")
    parts.append(f"[Current Question]\n{question}")
    return "\n\n".join(parts)