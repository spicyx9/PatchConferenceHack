"""Small deterministic text helpers shared by the planner and networking agents."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable

# Canonical person roles (core ``Person.roles`` literal) and the words that map to them.
ROLE_ALIASES: dict[str, str] = {
    "investor": "investor", "investors": "investor", "vc": "investor", "vcs": "investor",
    "seed investor": "investor", "seed investors": "investor", "angel": "investor",
    "business angel": "investor", "partner": "investor", "general partner": "investor",
    "founder": "founder", "founders": "founder", "co founder": "founder",
    "cofounder": "founder",
    "pm": "pm", "pms": "pm", "product manager": "pm", "product managers": "pm",
    "product lead": "pm", "head of product": "pm",
    "engineer": "engineer", "engineers": "engineer", "developer": "engineer",
    "developers": "engineer", "staff engineer": "engineer",
    "devrel": "devrel", "developer advocate": "devrel",
    "executive": "executive", "vp": "executive", "cto": "executive",
}


def fold(text: str) -> str:
    """Lowercase, strip accents, turn punctuation into single spaces."""
    norm = unicodedata.normalize("NFKD", text)
    ascii_text = "".join(c for c in norm if not unicodedata.combining(c)).lower()
    return re.sub(r"[^a-z0-9]+", " ", ascii_text).strip()


def topic_key(topic: str) -> str:
    key = fold(topic)
    # "agent"/"agents", "ai agent"/"ai agents" are the same topic.
    return re.sub(r"\b(agent|tool|investor|founder)s\b", r"\1", key)


def topic_set(topics: Iterable[str]) -> set[str]:
    return {topic_key(t) for t in topics if t and topic_key(t)}


def canonical_role(role: str) -> str:
    key = fold(role)
    return ROLE_ALIASES.get(key, key)


def role_set(roles: Iterable[str]) -> set[str]:
    return {canonical_role(r) for r in roles if r and fold(r)}


def roles_from_title(title: str | None) -> set[str]:
    """Roles readable from a free-text title; weaker evidence than ``Person.roles``."""
    if not title:
        return set()
    folded = f" {fold(title)} "
    found = set()
    for alias, role in ROLE_ALIASES.items():
        if len(alias) > 2 and f" {alias} " in folded:
            found.add(role)
    return found
