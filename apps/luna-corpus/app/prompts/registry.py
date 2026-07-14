"""Template loading: file-default layer + DB-override layer + in-memory cache."""
from sqlalchemy.orm import Session

from app.db.models import PromptVersion
from app.observability.logging import get_logger
from app.prompts.defaults import (
    DEFAULT_TEMPLATES,
    RAG_QA_PROMPT_KEY,
    default_version_id,
)
from app.prompts.schemas import ResolvedTemplate

logger = get_logger("luna.prompts.registry")

# version_id -> ResolvedTemplate (DB rows only; file defaults are cheap to rebuild)
_CACHE: dict[str, ResolvedTemplate] = {}


def get_default_template(prompt_key: str, lang: str) -> ResolvedTemplate:
    """File-default layer. Never touches the DB. Always returns something."""
    entry = DEFAULT_TEMPLATES.get((prompt_key, lang))
    resolved_lang = lang
    if entry is None:
        entry = DEFAULT_TEMPLATES.get((prompt_key, "zh"))
        resolved_lang = "zh"
    if entry is None:
        entry = DEFAULT_TEMPLATES[(RAG_QA_PROMPT_KEY, "zh")]
        prompt_key, resolved_lang = RAG_QA_PROMPT_KEY, "zh"
    return ResolvedTemplate(
        version_id=default_version_id(prompt_key, resolved_lang),
        prompt_key=prompt_key,
        lang=resolved_lang,
        version_label=entry["version_label"],
        template_text=entry["template_text"],
    )


def get_template_by_version_id(
    db: Session, version_id: str, prompt_key: str, lang: str
) -> ResolvedTemplate:
    """Resolve a template by version id, falling back to the file default."""
    if not version_id or version_id.startswith("file::"):
        return get_default_template(prompt_key, lang)
    cached = _CACHE.get(version_id)
    if cached is not None:
        return cached
    try:
        row = db.query(PromptVersion).filter(PromptVersion.id == version_id).first()
    except Exception:
        logger.warning("prompt_version_load_failed", version_id=version_id, exc_info=True)
        return get_default_template(prompt_key, lang)
    if row is None:
        return get_default_template(prompt_key, lang)
    resolved = ResolvedTemplate(
        version_id=row.id,
        prompt_key=row.prompt_key,
        lang=row.lang,
        version_label=row.version_label,
        template_text=row.template_text,
    )
    _CACHE[version_id] = resolved
    return resolved


def invalidate(version_id: str) -> None:
    _CACHE.pop(version_id, None)


def invalidate_all() -> None:
    _CACHE.clear()
