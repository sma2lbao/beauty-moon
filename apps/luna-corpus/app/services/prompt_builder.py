"""Prompt rendering. Template selection lives in app.prompts.experiment."""
from app.prompts.defaults import RAG_QA_PROMPT_KEY, render_rag_body
from app.prompts.registry import get_default_template


def render_prompt(
    template_text: str,
    question: str,
    context: str,
    conversation_history: str = "",
    conversation_summary: str | None = None,
) -> str:
    """Fill a template's {body} placeholder with the assembled sections."""
    body = render_rag_body(
        question=question,
        context=context,
        conversation_history=conversation_history,
        conversation_summary=conversation_summary,
    )
    return template_text.replace("{body}", body)


def build_rag_prompt(
    question: str,
    context: str,
    conversation_history: str = "",
    conversation_summary: str | None = None,
) -> str:
    """Backward-compatible helper: render with the zh file-default template."""
    tpl = get_default_template(RAG_QA_PROMPT_KEY, "zh")
    return render_prompt(
        tpl.template_text, question, context, conversation_history, conversation_summary
    )


def build_rag_prompt_en(
    question: str,
    context: str,
    conversation_history: str = "",
    conversation_summary: str | None = None,
) -> str:
    """Backward-compatible helper: render with the en file-default template."""
    tpl = get_default_template(RAG_QA_PROMPT_KEY, "en")
    return render_prompt(
        tpl.template_text, question, context, conversation_history, conversation_summary
    )