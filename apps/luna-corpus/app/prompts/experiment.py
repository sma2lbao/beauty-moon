"""Per-KB experiment lookup + stable-hash traffic split. Never raises."""
import hashlib

from sqlalchemy.orm import Session

from app.db.models import ExperimentStatus, PromptExperiment
from app.observability.logging import get_logger
from app.prompts import registry
from app.prompts.schemas import ResolvedTemplate

logger = get_logger("luna.prompts.experiment")


def stable_bucket(seed: str, prompt_key: str) -> int:
    """Reproducible 0..99 bucket from a seed + prompt key."""
    digest = hashlib.sha256(f"{seed}:{prompt_key}".encode()).hexdigest()
    return int(digest, 16) % 100


def pick_version_id(variants: list[dict], bucket: int) -> str | None:
    """Map a bucket into a variant by cumulative weight."""
    total = sum(int(v.get("weight", 0)) for v in variants)
    if total <= 0:
        return None
    # scale bucket (0..99) onto 0..total
    threshold = bucket * total / 100.0
    cumulative = 0.0
    for v in variants:
        cumulative += int(v.get("weight", 0))
        if threshold < cumulative:
            return v.get("version_id")
    return variants[-1].get("version_id")


def select_version(
    db: Session,
    knowledge_base_id: str,
    prompt_key: str,
    lang: str,
    seed: str,
) -> ResolvedTemplate:
    """Choose the template for this request. Falls back to file default on
    any missing experiment or error."""
    try:
        exp = (
            db.query(PromptExperiment)
            .filter(
                PromptExperiment.knowledge_base_id == knowledge_base_id,
                PromptExperiment.prompt_key == prompt_key,
                PromptExperiment.status == ExperimentStatus.RUNNING,
            )
            .first()
        )
        if exp is None or not exp.variants:
            return registry.get_default_template(prompt_key, lang)
        bucket = stable_bucket(seed, prompt_key)
        version_id = pick_version_id(exp.variants, bucket)
        if not version_id:
            return registry.get_default_template(prompt_key, lang)
        return registry.get_template_by_version_id(db, version_id, prompt_key, lang)
    except Exception:
        logger.warning(
            "select_version_failed",
            knowledge_base_id=knowledge_base_id,
            prompt_key=prompt_key,
            exc_info=True,
        )
        return registry.get_default_template(prompt_key, lang)
