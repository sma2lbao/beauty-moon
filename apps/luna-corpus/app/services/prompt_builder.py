"""Prompt builder with conversation memory integration."""


def build_rag_prompt(
    question: str,
    context: str,
    conversation_history: str = "",
    conversation_summary: str | None = None,
) -> str:
    """Build complete RAG prompt with optional conversation context.

    Args:
        question: User question
        context: Retrieved document context
        conversation_history: Formatted conversation history
        conversation_summary: Optional summary of prior conversation

    Returns:
        Complete prompt for LLM
    """
    parts = []

    if conversation_summary:
        parts.append(f"[Prior Conversation Summary]\n{conversation_summary}\n")

    if conversation_history:
        parts.append(f"[Current Conversation]\n{conversation_history}\n")

    if context:
        parts.append(f"[Relevant Documents]\n{context}\n")

    parts.append(f"[Current Question]\n{question}")

    body = "\n\n".join(parts)

    prompt = f"""你是一个基于文档的问答助手。请根据提供的上下文信息回答问题。

{body}

请基于上述信息给出回答。如果上下文中没有相关信息，请说明无法从提供的文档中找到答案。"""

    return prompt


def build_rag_prompt_en(
    question: str,
    context: str,
    conversation_history: str = "",
    conversation_summary: str | None = None,
) -> str:
    """Build complete RAG prompt with optional conversation context (English).

    Args:
        question: User question
        context: Retrieved document context
        conversation_history: Formatted conversation history
        conversation_summary: Optional summary of prior conversation

    Returns:
        Complete prompt for LLM
    """
    parts = []

    if conversation_summary:
        parts.append(f"[Prior Conversation Summary]\n{conversation_summary}\n")

    if conversation_history:
        parts.append(f"[Current Conversation]\n{conversation_history}\n")

    if context:
        parts.append(f"[Relevant Documents]\n{context}\n")

    parts.append(f"[Current Question]\n{question}")

    body = "\n\n".join(parts)

    prompt = f"""You are a document-based Q&A assistant. Please answer questions based on the provided context.

{body}

Please provide your answer based on the above information. If the relevant information is not found in the context, please indicate that you cannot find an answer from the provided documents."""

    return prompt
