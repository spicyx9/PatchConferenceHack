"""Smart networking: who to meet, why, where, how, presence and confidence.

Deterministic pre-selection and U(o) scoring from the planner, then graph-style
adjustments: people already MET or CONTACTED leave the list, a company already
covered (by a met contact or a higher-ranked pick) loses its novelty, confirmed
presence is rewarded through P, and a short goal path in the graph adds a small
bonus when the graph is connected.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from conferge.agents.planner.candidates import (
    World,
    cite,
    event_label,
    person_candidate,
)
from conferge.agents.planner.scoring import DEFAULT_WEIGHTS, ScoreBreakdown, Weights, score_candidate
from conferge.agents.planner.text import topic_set
from conferge.core.schemas import Event, Opportunity, Person

GRAPH_BONUS_SHORT = 0.03    # path of <= 3 hops
GRAPH_BONUS_LONG = 0.015    # any longer path


@dataclass
class GraphHint:
    hops: int | None
    text: str


def _opener(person: Person, event: Event | None, presence: str, goal_topics: set[str]) -> str:
    first = person.name.split(" ")[0]
    shared = [t for t in person.topics if topic_set([t]) & goal_topics]
    topic = shared[0] if shared else (person.topics[0] if person.topics else "what you are building")
    if event is not None and presence == "confirmed":
        verb = "talk" if person.id in event.speaker_ids or event.event_type == "session" else "event"
        return f"Hi {first}, I am coming to your {verb} '{event.title}'; how are you approaching {topic}?"
    return f"Hi {first}, I am building in {topic} too; would you have 10 minutes this week?"


def recommend(world: World, *, weights: Weights = DEFAULT_WEIGHTS,
              graph_hints: dict[str, GraphHint] | None = None,
              limit: int | None = 10) -> tuple[list[Opportunity], list[dict[str, object]]]:
    """Return ranked person opportunities and decisions for excluded people."""
    graph_hints = graph_hints or {}
    excluded: list[dict[str, object]] = []
    built = []
    for person in sorted(world.ctx.people, key=lambda p: p.id):
        if person.id in world.met:
            excluded.append({"type": "excluded_person", "person_id": person.id,
                             "reason": "already met or contacted (memory)"})
            continue
        made = person_candidate(world, person)
        if made is None:
            continue
        cand, event, presence = made
        hint = graph_hints.get(person.id)
        if hint is not None:
            bonus = GRAPH_BONUS_SHORT if hint.hops is not None and hint.hops <= 3 else GRAPH_BONUS_LONG
            cand.bonus = bonus
            cand.facts.append(f"graph path ({hint.hops} hops): {hint.text}")
        built.append((person, cand, event, presence))

    def ranked(items):  # type: ignore[no-untyped-def]
        scored = [(score_candidate(c, weights), p, c, e, pr) for p, c, e, pr in items]
        return sorted(scored, key=lambda t: (-t[0].score, t[1].id))

    # Company coverage: a second pick from the same company is less novel.
    seen_companies: dict[str, str] = {}
    adjusted = []
    for _, person, cand, event, presence in ranked(built):
        company = person.company_id
        if company and company in seen_companies and cand.novelty > 0.5:
            cand = replace(cand, novelty=0.5, notes={
                **cand.notes, "N": f"company {company} already represented by {seen_companies[company]}"})
        if company:
            seen_companies.setdefault(company, person.name)
        adjusted.append((person, cand, event, presence))

    goal_topics = {t for g in world.ctx.goals for t in topic_set(g.topics)}
    opportunities = []
    for breakdown, person, cand, event, presence in ranked(adjusted):
        opportunities.append(_to_opportunity(person, cand, event, presence, breakdown, goal_topics))
    if limit is not None:
        opportunities = opportunities[:limit]
    return opportunities, excluded


def _to_opportunity(person: Person, cand, event: Event | None, presence: str,  # type: ignore[no-untyped-def]
                    breakdown: ScoreBreakdown, goal_topics: set[str]) -> Opportunity:
    warnings: list[str] = []
    if presence == "probable":
        warnings.append("presence probable: listed or linked, not a confirmed attendance")
    elif presence == "unknown":
        warnings.append("presence unknown: no source places this person at a dated event")
    evidence = list(person.evidence) + (list(event.evidence) if event else [])
    if any(e.source_mode == "fixture" for e in evidence):
        warnings.append("built from fixture records: not live data")
    rationale = f"{breakdown.explanation}. Facts: " + " | ".join(cand.facts)
    return Opportunity(
        id=f"opp-person-{person.id}",
        title=person.name + (f", {person.title}" if person.title else ""),
        goal_ids=cand.goal_ids,
        event_id=event.id if event else None,
        person_ids=[person.id],
        company_ids=[person.company_id] if person.company_id else [],
        score=breakdown.score,
        rationale=rationale,
        path=cand.path,
        where=event_label(event) if event else None,
        opener=_opener(person, event, presence, goal_topics),
        presence=presence,  # type: ignore[arg-type]
        evidence=evidence,
        warnings=warnings,
    )


__all__ = ["GraphHint", "cite", "recommend"]
