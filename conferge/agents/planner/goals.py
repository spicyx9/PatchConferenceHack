"""Deterministic goal parser: free text -> weighted ``Goal`` list.

No LLM key is available on hackathon night, so parsing is rule based. The
guardrail (Devoxx ``InterestValidatorAgent`` pattern) validates and cleans the
result: empty or incoherent text yields the documented default profile goals,
tagged ``default:*`` so the caller can see nothing was extracted, and
``goal_warnings()`` turns that into a visible envelope warning.

This module is the single rule set: ``conferge.api.logic.parse_goals`` delegates
here so the API fallback and the planner agent always agree on goal ids.

Weights follow mention order and always sum to 1 (demo text: 0.45/0.35/0.20).
"""

from __future__ import annotations

import re

from conferge.agents.planner.text import ROLE_ALIASES, fold
from conferge.core.schemas import Goal

PARSER_TAG = "parsed:planner-rules"
UNKNOWN_ROLE_WARNING = "role unknown: using default goals"
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
    r"\b(rencontrer|meet|meeting|connect with|network with|voir|talk to|parler a|parler avec|"
    r"trouver|find|looking for|look for|cherche|recherche|a la recherche de|discuter avec|"
    r"echanger avec|chat with|get in front of|introduced to|intros? to|pitch(?: to)?|pitcher a|"
    r"hiring(?! managers?)|hire|recruter|recrute)\b"
)
_SELF = re.compile(r"^(i am|i m|im|je suis|as an?|en tant que)\b.*?(\bsepx\b|$)")
_LIKE_ME = re.compile(r"\b(people like me|folks like me|others like me|peers|gens comme moi|"
                      r"personnes comme moi|mes pairs|pairs)\b")
_SEPARATORS = re.compile(r"[,;&/\n]+")
_SPLIT = re.compile(r"\bsepx\b|\bet\b|\band\b|\bainsi que\b|\bplus\b|\bpuis\b")
_SEED = re.compile(r"\b(seed|pre seed|amorcage|angel|angels|business angel)\b")


def _forms(stem: str, role: str, *suffixes: str) -> dict[str, str]:
    return {stem + s: role for s in ("", *suffixes)}


# French and English role words, folded (no accents). Longest alias wins and hides its
# tail, so "security engineers" is one role, not security + engineer.
_ROLE_WORDS: dict[str, str] = {
    **ROLE_ALIASES,
    **_forms("investisseur", "investor", "s"),
    **_forms("angel investor", "investor", "s"),
    **_forms("business angel", "investor", "s"),
    **_forms("fondateur", "founder", "s"), **_forms("fondatrice", "founder", "s"),
    **_forms("cofondateur", "founder", "s"), **_forms("co fondateur", "founder", "s"),
    **_forms("startup founder", "founder", "s"), **_forms("solo founder", "founder", "s"),
    "chef de produit": "pm", "chefs de produit": "pm",
    **_forms("product owner", "pm", "s"), **_forms("po", "pm", "s"),
    **_forms("ingenieur", "engineer", "s", "e", "es"),
    **_forms("developpeur", "engineer", "s"), **_forms("developpeuse", "engineer", "s"),
    **_forms("dev", "engineer", "s"), **_forms("maintainer", "engineer", "s"),
    **_forms("mainteneur", "engineer", "s"), **_forms("platform engineer", "engineer", "s"),
    **_forms("backend engineer", "engineer", "s"), **_forms("software engineer", "engineer", "s"),
    **_forms("architecte", "engineer", "s"), **_forms("architect", "engineer", "s"),
    **_forms("developer advocate", "devrel", "s"), **_forms("devrel", "devrel", "s"),
    "dev rel": "devrel", "developer relations": "devrel", "relations developpeurs": "devrel",
    **_forms("evangelist", "devrel", "s"), **_forms("evangeliste", "devrel", "s"),
    **_forms("community manager", "devrel", "s"),
    **_forms("cto", "executive", "s"), **_forms("ceo", "executive", "s"),
    **_forms("cio", "executive", "s"), **_forms("coo", "executive", "s"),
    **_forms("ciso", "executive", "s"), **_forms("rssi", "executive"),
    **_forms("cxo", "executive", "s"), "c level": "executive", "c levels": "executive",
    "vps": "executive", **_forms("vp of engineering", "executive"),
    **_forms("vp engineering", "executive"), "directeur technique": "executive", "directeurs techniques": "executive",
    "directrice technique": "executive", **_forms("dirigeant", "executive", "s", "e", "es"),
    **_forms("decideur", "executive", "s"), **_forms("head of engineering", "executive"),
    **_forms("chief technology officer", "executive", "s"),
    **_forms("recruiter", "recruiter", "s"), **_forms("recruteur", "recruiter", "s"), **_forms("recruteuse", "recruiter", "s"),
    **_forms("hiring manager", "recruiter", "s"), **_forms("talent partner", "recruiter", "s"),
    **_forms("head of talent", "recruiter"), **_forms("talent acquisition", "recruiter"),
    "chasseur de tetes": "recruiter", "chasseurs de tetes": "recruiter",
    **_forms("designer", "designer", "s"), **_forms("product designer", "designer", "s"),
    **_forms("ux designer", "designer", "s"), **_forms("ui designer", "designer", "s"),
    **_forms("ux researcher", "designer", "s"), "chercheur ux": "designer", "chercheurs ux": "designer", "chercheuse ux": "designer", "designer produit": "designer", "designers produit": "designer", "design lead": "designer", "design leads": "designer",
    "head of design": "designer",
    **_forms("data scientist", "data", "s"), **_forms("data engineer", "data", "s"),
    **_forms("data analyst", "data", "s"), **_forms("ml engineer", "data", "s"),
    **_forms("machine learning engineer", "data", "s"), "ingenieur ml": "data", "ingenieurs ml": "data", "ingenieur data": "data", "ingenieurs data": "data",
    **_forms("data team", "data", "s"), "data people": "data", "head of data": "data",
    **_forms("security engineer", "security", "s"), **_forms("security researcher", "security", "s"),
    **_forms("security lead", "security", "s"), "security people": "security",
    "security folks": "security", **_forms("pentester", "security", "s"),
    **_forms("appsec engineer", "security", "s"), "ingenieur securite": "security", "ingenieurs securite": "security", "responsable securite": "security", "responsables securite": "security",
    "expert securite": "security", "experts securite": "security",
    "expert en securite": "security", "experts en securite": "security",
    "head of security": "security",
}
_TOPIC_WORDS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b(ai )?agents?\b|\bagentic\b"), "ai agents"),
    (re.compile(r"\bcopilot\b"), "copilot"),
    (re.compile(r"\bmcp\b"), "mcp"),
    (re.compile(r"\b(dev ?tools?|developer tools?|outils? (de )?dev\w*|devtools?|tooling)\b"),
     "developer tools"),
    (re.compile(r"\b(llm|llms|genai|gen ai)\b"), "llm"),
    (re.compile(r"\b(fintech|fintechs|payments?|paiements?|banking|banque|banques|bank|banks|"
                r"finance|insurtech|neobank|neobanque)\b"), "fintech"),
    (re.compile(r"\b(security|securite|cyber ?security|cybersecurite|cyber|appsec|infosec|"
                r"pentest|zero trust)\b"), "security"),
    (re.compile(r"\b(open ?source|oss|opensource|maintainers?|libre)\b"), "open source"),
    (re.compile(r"\b(data|donnees|analytics|ml|machine learning)\b"), "data"),
    (re.compile(r"\b(design|ux|ui|user experience|product design)\b"), "design"),
    (re.compile(r"\b(infra|infrastructure|cloud|kubernetes|k8s|devops|platform|platforms|"
                r"plateforme|sre|serverless)\b"), "infra"),
]
_ROLE_LABEL = {
    "investor": "investors", "founder": "founders", "pm": "product managers",
    "engineer": "engineers", "devrel": "developer advocates", "executive": "executives",
    "recruiter": "recruiters", "designer": "designers", "data": "data scientists",
    "security": "security engineers",
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
_ROLE_WORDS_BY_LENGTH = sorted(_ROLE_WORDS, key=len, reverse=True)


def _defaults() -> list[Goal]:
    """Fresh copies of the default goals, tagged so nothing is silent."""
    goals = [g.model_copy(deep=True) for g in DEFAULT_GOALS]
    for g in goals:
        if UNKNOWN_ROLE_WARNING not in g.tags:
            g.tags.append(UNKNOWN_ROLE_WARNING)
    return goals


def is_default(goals: list[Goal]) -> bool:
    return not goals or any(t.startswith("default:") for g in goals for t in g.tags)


def goal_warnings(goals: list[Goal]) -> list[str]:
    """Envelope warnings for a parsed goal list (empty when a role was recognised)."""
    return [UNKNOWN_ROLE_WARNING] if is_default(goals) else []


def _topics(text: str) -> list[str]:
    found: list[str] = []
    for pattern, topic in _TOPIC_WORDS:
        if pattern.search(text) and topic not in found:
            found.append(topic)
    return found


def _roles_in(clause: str) -> list[tuple[int, str]]:
    padded = f" {clause} "
    hits: dict[str, int] = {}
    # Longest aliases first so "product managers" wins over a bare "pm" and
    # "security engineers" hides its "engineers" tail.
    for word in _ROLE_WORDS_BY_LENGTH:
        needle = f" {word} "
        index = padded.find(needle)
        while index >= 0:
            role = _ROLE_WORDS[word]
            hits[role] = min(hits.get(role, index), index)
            padded = padded[:index] + " " * len(needle) + padded[index + len(needle):]
            index = padded.find(needle)
    return sorted(((pos, role) for role, pos in hits.items()))


def _describe(role: str, clause: str, topics: list[str]) -> str:
    label = _ROLE_LABEL.get(role, role)
    if role == "investor" and _SEED.search(clause):
        label = "seed investors"
    if topics:
        return f"Meet {label} ({', '.join(topics)})"
    return f"Meet {label}"


def _slug(role: str, clause: str, topics: list[str]) -> str:
    """Stable ids; the three demo goals keep the ids the demo fixtures use."""
    if role == "investor" and _SEED.search(clause):
        return "goal-seed-investors"
    if role == "founder" and "ai agents" in topics:
        return "goal-agent-founders"
    if role == "pm" and "copilot" in topics:
        return "goal-copilot-pms"
    return f"goal-{role}"


def parse_goals(text: str | None) -> list[Goal]:
    """Extract weighted goals. Never raises; falls back to tagged ``DEFAULT_GOALS``."""
    # fold() drops punctuation, so mark clause separators with a token first.
    folded = fold(_SEPARATORS.sub(" sepx ", text or ""))
    if not folded or not folded.replace("sepx", "").strip():
        return _defaults()
    trigger = _TRIGGER.search(folded)
    if trigger:
        profile, wanted = folded[: trigger.start()], folded[trigger.end():]
    else:
        # No "meet" verb: a leading self-description ("I am a founder") is the user, not a goal.
        self_desc = _SELF.match(folded)
        profile, wanted = (self_desc.group(0), folded[self_desc.end():]) if self_desc else ("", folded)
    profile_topics = _topics(profile)
    all_topics = _topics(folded)

    raw: list[tuple[str, str, list[str], int | None]] = []
    for clause in (c.strip() for c in _SPLIT.split(wanted)):
        if not clause:
            continue
        roles = _roles_in(clause)
        if not roles and _LIKE_ME.search(clause):
            roles = _roles_in(profile)  # "people like me": the user's own role is the target
        for _, role in roles:
            if any(existing == role for existing, *_ in raw):
                continue
            topics = _topics(clause) or profile_topics or all_topics
            count = _NUMBER.search(clause)
            raw.append((role, clause, topics, int(count.group(1)) if count else None))

    if not raw and trigger and wanted != folded:
        # The verb split left no role after it ("Recruiters hiring ..."): scan everything.
        for _, role in _roles_in(folded):
            raw.append((role, folded, all_topics, None))
    # Guardrail: nothing usable means defaults, visibly tagged.
    if not raw:
        return _defaults()
    raw = raw[:MAX_GOALS]
    weights = WEIGHT_TABLE[len(raw)]
    goals: list[Goal] = []
    used_ids: set[str] = set()
    for (role, clause, topics, count), weight in zip(raw, weights, strict=True):
        goal_id = _slug(role, clause, topics)
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
