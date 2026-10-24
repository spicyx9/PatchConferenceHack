"""Deterministic goal parser: free text -> weighted ``Goal`` list.

No LLM key is available on hackathon night, so parsing is rule based. The
guardrail (Devoxx ``InterestValidatorAgent`` pattern) validates and cleans the
result: empty or incoherent text yields the documented default profile goals,
tagged ``default:*`` so the caller can see nothing was extracted.

Weights follow mention order and always sum to 1 (demo text: 0.45/0.35/0.20).
"""

from __future__ import annotations

import re

from conferge.agents.planner.text import ROLE_ALIASES, fold
from conferge.core.schemas import Goal

PARSER_TAG = "parsed:planner-rules"
# Mention-order weights per goal count; each row sums to 1.
WEIGHT_TABLE: dict[int, list[float]] = {
    1: [1.0],
    2: [0.6, 0.4],
    3: [0.45, 0.35, 0.20],
    4: [0.4, 0.3, 0.2, 0.1],
    5: [0.35, 0.25, 0.2, 0.12, 0.08],
}
MAX_GOALS = max(WEIGHT_TABLE)

# Words introducing who the user wants to meet; text before them describes the user.
_TRIGGER = re.compile(
    r"\b(rencontrer|meet|meeting|connect with|network with|voir|talk to|parler a|trouver|find)\b"
)
_SELF = re.compile(r"^(i am|i m|im|je suis|as an?|en tant que)\b.*?(\bsepx\b|$)")
_SEPARATORS = re.compile(r"[,;&/\n]+")
_SPLIT = re.compile(r"\bsepx\b|\bet\b|\band\b|\bainsi que\b|\bplus\b|\bpuis\b")
# French and English role words, folded (no accents).
_ROLE_WORDS: dict[str, str] = {
    **ROLE_ALIASES,
    "investisseur": "investor", "investisseurs": "investor",
    "fondateur": "founder", "fondateurs": "founder", "fondatrice": "founder",
    "fondatrices": "founder", "cofondateur": "founder", "cofondateurs": "founder",
    "chef de produit": "pm", "chefs de produit": "pm",
    "ingenieur": "engineer", "ingenieurs": "engineer",
    "developpeur": "engineer", "developpeurs": "engineer",
}
_TOPIC_WORDS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bagents?\b"), "ai agents"),
    (re.compile(r"\bcopilot\b"), "copilot"),
    (re.compile(r"\bmcp\b"), "mcp"),
    (re.compile(r"\b(dev ?tools?|developer tools?|outils? (de )?dev\w*|devtools?)\b"),
     "developer tools"),
    (re.compile(r"\b(llm|genai|gen ai)\b"), "llm"),
]
_ROLE_LABEL = {
    "investor": "investors", "founder": "founders", "pm": "product managers",
    "engineer": "engineers", "devrel": "developer advocates", "executive": "executives",
}
_NUMBER = re.compile(r"\b(\d{1,2})\b")

DEFAULT_GOALS: list[Goal] = [
    Goal(id="goal-seed-investors", description="Meet seed investors active in developer tools",
         priority=0.45, target_roles=["investor"], topics=["developer tools", "ai agents"],
         tags=["default:no-goal-recognised"]),
    Goal(id="goal-agent-founders", description="Meet founders building AI agents",
         priority=0.35, target_roles=["founder"], topics=["ai agents", "mcp"],
         tags=["default:no-goal-recognised"]),
    Goal(id="goal-copilot-pms", description="Meet Copilot product managers",
         priority=0.20, target_roles=["pm"], topics=["copilot", "mcp"],
         tags=["default:no-goal-recognised"]),
]


def _topics(text: str) -> list[str]:
    found: list[str] = []
    for pattern, topic in _TOPIC_WORDS:
        if pattern.search(text) and topic not in found:
            found.append(topic)
    return found


def _roles_in(clause: str) -> list[tuple[int, str]]:
    padded = f" {clause} "
    hits: dict[str, int] = {}
    # Longest aliases first so "product managers" wins over a bare "pm".
    for word in sorted(_ROLE_WORDS, key=len, reverse=True):
        index = padded.find(f" {word} ")
        if index >= 0:
            role = _ROLE_WORDS[word]
            hits[role] = min(hits.get(role, index), index)
    return sorted(((pos, role) for role, pos in hits.items()))


def _describe(role: str, clause: str, topics: list[str]) -> str:
    label = _ROLE_LABEL.get(role, role)
    if role == "investor" and re.search(r"\b(seed|pre seed|amorcage)\b", clause):
        label = "seed investors"
    if topics:
        return f"Meet {label} ({', '.join(topics)})"
    return f"Meet {label}"


def _slug(role: str, clause: str) -> str:
    if role == "investor" and "seed" in clause:
        return "goal-seed-investors"
    return f"goal-{role}"


def parse_goals(text: str | None) -> list[Goal]:
    """Extract weighted goals. Never raises; falls back to ``DEFAULT_GOALS``."""
    # fold() drops punctuation, so mark clause separators with a token first.
    folded = fold(_SEPARATORS.sub(" sepx ", text or ""))
    if not folded:
        return [g.model_copy(deep=True) for g in DEFAULT_GOALS]
    trigger = _TRIGGER.search(folded)
    if trigger:
        profile, wanted = folded[: trigger.start()], folded[trigger.end():]
    else:
        # No "meet" verb: a leading self-description ("I am a founder") is the user, not a goal.
        self_desc = _SELF.match(folded)
        profile, wanted = (self_desc.group(0), folded[self_desc.end():]) if self_desc else ("", folded)
    profile_topics = _topics(profile)
    if not folded.replace("sepx", "").strip():
        return [g.model_copy(deep=True) for g in DEFAULT_GOALS]
    all_topics = _topics(folded)

    raw: list[tuple[str, str, list[str], int | None]] = []
    for clause in (c.strip() for c in _SPLIT.split(wanted)):
        if not clause:
            continue
        for _, role in _roles_in(clause):
            if any(existing == role for existing, *_ in raw):
                continue
            topics = _topics(clause) or profile_topics or all_topics
            count = _NUMBER.search(clause)
            raw.append((role, clause, topics, int(count.group(1)) if count else None))

    # Guardrail: nothing usable means defaults, visibly tagged.
    if not raw:
        return [g.model_copy(deep=True) for g in DEFAULT_GOALS]
    raw = raw[:MAX_GOALS]
    weights = WEIGHT_TABLE[len(raw)]
    goals: list[Goal] = []
    used_ids: set[str] = set()
    for (role, clause, topics, count), weight in zip(raw, weights, strict=True):
        goal_id = _slug(role, clause)
        if goal_id in used_ids:
            goal_id = f"{goal_id}-{len(used_ids) + 1}"
        used_ids.add(goal_id)
        goals.append(Goal(
            id=goal_id, description=_describe(role, clause, topics), priority=weight,
            target_roles=[role], topics=topics, target_count=count, tags=[PARSER_TAG],
        ))
    return goals


def normalized_weights(goals: list[Goal]) -> dict[str, float]:
    """Goal weights rescaled to sum to 1 (input priorities may not)."""
    total = sum(g.priority for g in goals)
    if total <= 0:
        return {g.id: 1.0 / len(goals) for g in goals} if goals else {}
    return {g.id: g.priority / total for g in goals}
