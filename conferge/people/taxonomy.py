"""Short topic taxonomy and title -> role rules (docs/knowledge/08-people.md).

Deterministic keyword matching is the default. An LLM extractor can be injected
(`TopicExtractor`) but its output is always clipped to this taxonomy.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from typing import Protocol

TOPICS: dict[str, tuple[str, ...]] = {
    "ai agents": ("ai agent", "agentic", "agents", "autonomous agent", "multi-agent",
                  "coding agent"),
    "developer tools": ("developer tool", "devtool", "developer experience", "dev tool",
                        "developer productivity", "ide", "devex"),
    "mcp": ("mcp", "model context protocol"),
    "copilot": ("copilot",),
    "devsecops": ("devsecops", "security", "appsec", "supply chain", "vulnerab",
                  "secret scanning", "codeql"),
    "infra": ("infrastructure", "kubernetes", "cloud", "platform engineering", "devops",
              "ci/cd", "actions", "sre"),
    "llm": ("llm", "large language model", "genai", "generative ai", "foundation model"),
    "open source": ("open source", "oss", "maintainer"),
    "seed investor": ("seed stage", "seed-stage", "seed investor", "seed fund", "pre-seed",
                      "venture capital", "vc fund", "angel investor"),
    "enterprise": ("enterprise", "governance", "compliance"),
}

# Ordered: first match wins for ambiguous words; several roles may apply.
_ROLE_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("founder", ("founder", "co-founder", "cofounder")),
    ("investor", ("investor", "venture partner", "general partner", "managing partner",
                  "principal at", "angel")),
    ("pm", ("product manager", "product management", "product lead", "head of product",
            "vp of product", "vp, product", "director of product", "product director",
            "product owner")),
    ("devrel", ("developer advocate", "developer relations", "devrel", "evangelist")),
    ("executive", ("chief", "ceo", "cto", "cio", "ciso", "coo", "president", "vp",
                   "vice president", "svp", "evp")),
    ("engineer", ("engineer", "developer", "architect", "programmer", "researcher")),
]

ROLE_ALIASES: dict[str, str] = {
    "investor": "investor", "investors": "investor", "vc": "investor", "vcs": "investor",
    "seed investor": "investor", "seed investors": "investor", "founder": "founder",
    "founders": "founder", "pm": "pm", "pms": "pm", "product manager": "pm",
    "product managers": "pm", "engineer": "engineer", "engineers": "engineer",
    "devrel": "devrel", "executive": "executive", "executives": "executive",
}


def fold(text: str) -> str:
    """Lowercase, strip accents, collapse whitespace."""
    norm = unicodedata.normalize("NFKD", text)
    norm = "".join(c for c in norm if not unicodedata.combining(c)).lower()
    return re.sub(r"\s+", " ", norm).strip()


def _contains(haystack: str, needle: str) -> bool:
    # Word boundary on the left so "ide" does not match "provide"; right side open
    # so "vulnerab" stems still match.
    return re.search(r"(?<![a-z0-9])" + re.escape(needle), haystack) is not None


def topics_from_text(*texts: str | None) -> list[str]:
    """Deterministic topics found in any of the texts, in taxonomy order."""
    blob = fold(" ".join(t for t in texts if t))
    if not blob:
        return []
    return [topic for topic, keys in TOPICS.items() if any(_contains(blob, k) for k in keys)]


def normalize_topics(values: Iterable[str]) -> list[str]:
    """Clip free-form topics (goals, LLM output) to the taxonomy; unknown ones dropped."""
    out: list[str] = []
    for value in values:
        key = fold(value)
        if key in TOPICS:
            found = [key]
        else:
            found = topics_from_text(value)
        for topic in found:
            if topic not in out:
                out.append(topic)
    return out


def roles_from_title(title: str | None) -> list[str]:
    if not title:
        return []
    text = fold(title)
    roles = [role for role, keys in _ROLE_RULES if any(_contains(text, k) for k in keys)]
    return roles


def normalize_roles(values: Iterable[str]) -> list[str]:
    out: list[str] = []
    for value in values:
        role = ROLE_ALIASES.get(fold(value))
        if role is None:
            found = roles_from_title(value)
            role = found[0] if found else None
        if role and role not in out:
            out.append(role)
    return out


class TopicExtractor(Protocol):
    """Optional LLM-backed extractor; output is clipped by `normalize_topics`."""

    async def extract(self, texts: list[str]) -> list[str]: ...


async def extract_topics(texts: list[str | None], extractor: TopicExtractor | None = None
                         ) -> tuple[list[str], str]:
    """Return (topics, method). Falls back to keywords if no extractor or it fails."""
    clean = [t for t in texts if t]
    base = topics_from_text(*clean)
    if extractor is None or not clean:
        return base, "keywords"
    try:
        extra = normalize_topics(await extractor.extract(clean))
    except Exception:  # noqa: BLE001 - any LLM failure falls back visibly
        return base, "keywords_fallback"
    merged = base + [t for t in extra if t not in base]
    return merged, "llm"
