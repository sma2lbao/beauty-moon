"""Structures shared across the prompts module."""
from dataclasses import dataclass


@dataclass
class ResolvedTemplate:
    """A concrete template chosen for one request."""

    version_id: str | None
    prompt_key: str
    lang: str
    version_label: str
    template_text: str


@dataclass
class Variant:
    """One arm of an A/B experiment."""

    version_id: str
    weight: int