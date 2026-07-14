from app.services.prompt_builder import build_rag_prompt, build_rag_prompt_en, render_prompt


def test_render_prompt_replaces_body():
    tpl = "PREFIX\n{body}\nSUFFIX"
    out = render_prompt(tpl, question="Q?", context="CTX")
    assert out.startswith("PREFIX")
    assert out.endswith("SUFFIX")
    assert "Q?" in out and "CTX" in out


def _legacy_build_rag_prompt(question, context, conversation_history="", conversation_summary=None):
    """Original inline body-assembly logic (pre-governance)."""
    parts = []
    if conversation_summary:
        parts.append(f"[Prior Conversation Summary]\n{conversation_summary}\n")
    if conversation_history:
        parts.append(f"[Current Conversation]\n{conversation_history}\n")
    if context:
        parts.append(f"[Relevant Documents]\n{context}\n")
    parts.append(f"[Current Question]\n{question}")
    body = "\n\n".join(parts)
    return f"""你是一个基于文档的问答助手。请根据提供的上下文信息回答问题。

{body}

请基于上述信息给出回答。如果上下文中没有相关信息，请说明无法从提供的文档中找到答案。"""


def _legacy_build_rag_prompt_en(question, context, conversation_history="", conversation_summary=None):
    """Original inline body-assembly logic (pre-governance) — English shell."""
    parts = []
    if conversation_summary:
        parts.append(f"[Prior Conversation Summary]\n{conversation_summary}\n")
    if conversation_history:
        parts.append(f"[Current Conversation]\n{conversation_history}\n")
    if context:
        parts.append(f"[Relevant Documents]\n{context}\n")
    parts.append(f"[Current Question]\n{question}")
    body = "\n\n".join(parts)
    return f"""You are a document-based Q&A assistant. Please answer questions based on the provided context.

{body}

Please provide your answer based on the above information. If the relevant information is not found in the context, please indicate that you cannot find an answer from the provided documents."""


def test_build_rag_prompt_backward_compatible():
    # 旧签名仍可用，输出含中文默认外壳
    out = build_rag_prompt(question="Q?", context="CTX")
    assert "基于文档的问答助手" in out
    assert "Q?" in out
    assert "CTX" in out

    # 逐字符等价性：新实现输出必须与原始实现完全一致
    cases = [
        # (question, context, conversation_history, conversation_summary, label)
        ("Q?", "CTX", "", None, "仅 question+context"),
        ("Q?", "CTX", "HIST", "SUMMARY", "question+context+history+summary 全量"),
        ("Q?", "", "", None, "无 context"),
        ("Q?", "CTX", "HIST", None, "question+context+history，无 summary"),
        ("Q?", "CTX", "", "SUMMARY", "question+context+summary，无 history"),
        ("Q?", "", "HIST", "SUMMARY", "无 context，有 history+summary"),
    ]
    for q, c, h, s, label in cases:
        actual = build_rag_prompt(question=q, context=c, conversation_history=h, conversation_summary=s)
        expected = _legacy_build_rag_prompt(question=q, context=c, conversation_history=h, conversation_summary=s)
        assert actual == expected, (
            f"等价性断言失败 [{label}]:\n"
            f"--- actual ---\n{actual!r}\n"
            f"--- expected ---\n{expected!r}"
        )


def test_build_rag_prompt_en_backward_compatible():
    # 英文版等价性断言
    out = build_rag_prompt_en(question="Q?", context="CTX")
    assert "document-based Q&A" in out
    assert "Q?" in out
    assert "CTX" in out

    cases = [
        ("Q?", "CTX", "", None, "仅 question+context"),
        ("Q?", "CTX", "HIST", "SUMMARY", "question+context+history+summary 全量"),
    ]
    for q, c, h, s, label in cases:
        actual = build_rag_prompt_en(question=q, context=c, conversation_history=h, conversation_summary=s)
        expected = _legacy_build_rag_prompt_en(question=q, context=c, conversation_history=h, conversation_summary=s)
        assert actual == expected, (
            f"英文等价性断言失败 [{label}]:\n"
            f"--- actual ---\n{actual!r}\n"
            f"--- expected ---\n{expected!r}"
        )
