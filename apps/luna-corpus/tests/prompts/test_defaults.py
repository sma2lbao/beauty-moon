from app.prompts.defaults import (
    DEFAULT_TEMPLATES,
    RAG_QA_PROMPT_KEY,
    default_version_id,
    render_rag_body,
)


def test_default_templates_have_zh_and_en():
    assert (RAG_QA_PROMPT_KEY, "zh") in DEFAULT_TEMPLATES
    assert (RAG_QA_PROMPT_KEY, "en") in DEFAULT_TEMPLATES


def test_default_template_has_body_placeholder():
    tpl = DEFAULT_TEMPLATES[(RAG_QA_PROMPT_KEY, "zh")]["template_text"]
    assert "{body}" in tpl


def test_render_body_includes_all_sections():
    body = render_rag_body(
        question="Q?",
        context="CTX",
        conversation_history="HIST",
        conversation_summary="SUM",
    )
    assert "SUM" in body and "HIST" in body and "CTX" in body and "Q?" in body


def test_render_body_minimal_only_question():
    body = render_rag_body(question="Q?", context="")
    assert "Q?" in body
    assert "[Relevant Documents]" not in body


def test_default_version_id_stable():
    assert default_version_id("rag_qa", "zh") == "file::rag_qa::zh"