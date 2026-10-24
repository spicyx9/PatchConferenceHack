"""Stage D: two-stage people ranking against weighted goals.

1. Deterministic shortlist: role and topic overlap with each goal, top `shortlist_size`.
2. Optional injected `Scorer` (LLM) on the top `llm_cap`; any failure falls back to the
   deterministic score with a visible warning. Works fully offline without any key.

Presence and "where" come only from published speaker/host presences and the event's own
time and venue. A relevant candidate is never reported as attending anything.
Graph bonuses and penalties (MET, CONTACTED, company coverage) belong to w09; this module
exposes the pure `apply_graph_adjustments` for them.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from conferge.core.schemas import DataMode, Event, Goal, RunStatus
from conferge.people.collect import combine_modes
from conferge.people.models import (
    PersonMatch,
    PersonProfile,
    PresenceStatus,
    ScoreBreakdown,
    WhereSlot,
    grade_for,
)
from conferge.people.taxonomy import normalize_roles, normalize_topics

ROLE_WEIGHT = 0.6
TOPIC_WEIGHT = 0.4
GOAL_POINTS = 80.0
PRESENCE_BONUS = {"confirmed": 12.0, "probable": 4.0, "unknown": 0.0}
IDENTITY_BONUS = 8.0
# Corroboration (ai-sdr contact_research): distinct providers among the person's evidence.
CORROBORATION_BONUS = ((2, 4.0), (3, 2.0))  # +4 from 2 sources, +2 more from 3


class LLMScore(BaseModel):
    model_config = ConfigDict(extra="forbid")
    goal_scores: dict[str, float] = Field(default_factory=dict)
    reason: str | None = None
    opener: str | None = None


class Scorer(Protocol):
    """Injected LLM scorer. Must only use facts present in the profile it receives."""

    async def score(self, profile: PersonProfile, goals: Sequence[Goal]) -> LLMScore: ...


@dataclass(frozen=True)
class GraphAdjustment:
    delta: float
    reason: str


@dataclass
class RankingResult:
    matches: list[PersonMatch]
    source_mode: DataMode
    status: RunStatus
    shortlisted: int
    considered: int
    scorer: str
    warnings: list[str] = field(default_factory=list)


def _goal_terms(goal: Goal) -> tuple[set[str], set[str]]:
    roles = set(normalize_roles(goal.target_roles))
    topics = set(normalize_topics([*goal.topics, *goal.tags]))
    return roles, topics


def goal_fit(profile: PersonProfile, goal: Goal) -> tuple[float, list[str]]:
    """0..1 fit of a person to one goal, with the matched role and topics."""
    roles, topics = _goal_terms(goal)
    person = profile.person
    role_hit = sorted(roles & set(person.roles))
    topic_hit = sorted(topics & set(person.topics))
    role_part = 1.0 if role_hit else 0.0
    topic_part = len(topic_hit) / len(topics) if topics else 0.0
    if roles and topics:
        value = ROLE_WEIGHT * role_part + TOPIC_WEIGHT * topic_part
    elif roles:
        value = role_part
    elif topics:
        value = topic_part
    else:
        value = 0.0
    return value, role_hit + topic_hit


def presence_status(profile: PersonProfile) -> PresenceStatus:
    statuses = {p.status for p in profile.presences}
    if "confirmed" in statuses:
        return "confirmed"
    if "probable" in statuses:
        return "probable"
    return "unknown"


def _weights(goals: Sequence[Goal]) -> dict[str, float]:
    total = sum(g.priority for g in goals) or float(len(goals) or 1)
    return {g.id: (g.priority or 1.0) / total for g in goals}


def source_count(profile: PersonProfile) -> int:
    """Distinct providers in the person's evidence and in the evidence of their presences."""
    evidence = [*profile.person.evidence, *(p.evidence for p in profile.presences)]
    return len({e.provider for e in evidence})


def breakdown(goal_scores: Mapping[str, float], weights: Mapping[str, float],
              profile: PersonProfile) -> ScoreBreakdown:
    base = sum(weights.get(gid, 0.0) * min(max(v, 0.0), 1.0) for gid, v in goal_scores.items())
    person = profile.person
    identity = IDENTITY_BONUS if (person.identity_confidence or 0) >= 0.9 and (
        person.linkedin_url or person.github_url) else 0.0
    sources = source_count(profile)
    return ScoreBreakdown.capped({
        "goal_fit": GOAL_POINTS * base,
        "presence": PRESENCE_BONUS[presence_status(profile)],
        "identity": identity,
        "corroboration": sum(bonus for floor, bonus in CORROBORATION_BONUS if sources >= floor),
    })


def _combine(goal_scores: Mapping[str, float], weights: Mapping[str, float],
             profile: PersonProfile) -> float:
    return breakdown(goal_scores, weights, profile).total()


def where_slots(profile: PersonProfile, events: Mapping[str, Event]) -> tuple[
        list[WhereSlot], list[str]]:
    slots: list[WhereSlot] = []
    warnings: list[str] = []
    for presence in profile.presences:
        if presence.status == "unknown":
            continue
        event = events.get(presence.event_id)
        if event is None:
            warnings.append(f"{profile.id}: event {presence.event_id} not loaded; no where slot")
            continue
        slots.append(WhereSlot(
            event_id=event.id, title=event.title, kind=presence.kind, status=presence.status,
            start_at=event.start_at, end_at=event.end_at,
            venue=event.venue.name if event.venue else None, room=event.room,
            source_url=event.source_url or presence.evidence.source_url,
        ))
    slots.sort(key=lambda s: (s.start_at is None, s.start_at.isoformat() if s.start_at else ""))
    return slots, warnings


def deterministic_opener(profile: PersonProfile, matched_topics: Iterable[str],
                         slots: Sequence[WhereSlot]) -> str:
    """Opener built only from published facts (talk title, hosted event, company, topic)."""
    topic = next(iter(matched_topics), None) or next(iter(profile.person.topics), None)
    company = profile.company_name
    angle = f" how you are approaching {topic}" if topic else " what you are working on"
    at = f" at {company}" if company else ""
    talk = next((s for s in slots if s.kind == "speaker"), None)
    if talk is not None:
        return f'I am looking forward to your session "{talk.title}". Curious{angle}{at}.'
    hosted = next((s for s in slots if s.kind == "host"), None)
    if hosted is not None:
        return f'Thanks for hosting "{hosted.title}". I would love to hear{angle}{at}.'
    return f"Hi {profile.person.name.split()[0]}, I would love to hear{angle}{at}."


def _reasons(profile: PersonProfile, goals: Sequence[Goal], fits: Mapping[str, tuple[float,
             list[str]]], slots: Sequence[WhereSlot]) -> list[str]:
    reasons = []
    for goal in goals:
        value, hits = fits[goal.id]
        if value > 0:
            reasons.append(f"Fits goal '{goal.description}' ({value:.2f}): {', '.join(hits)}")
    for slot in slots[:2]:
        verb = "Confirmed speaker" if slot.kind == "speaker" else "Confirmed host"
        reasons.append(f'{verb}: "{slot.title}"')
    if not slots:
        reasons.append("Relevant candidate only: no published presence at a loaded event")
    return reasons


def shortlist(profiles: Iterable[PersonProfile], goals: Sequence[Goal], *,
              size: int = 50) -> list[tuple[PersonProfile, dict[str, tuple[float, list[str]]],
                                             float]]:
    """Stage 1: keep people sharing at least one target role or topic, best first."""
    weights = _weights(goals)
    rows = []
    for profile in profiles:
        fits = {g.id: goal_fit(profile, g) for g in goals}
        if not any(v > 0 for v, _ in fits.values()):
            continue
        score = _combine({gid: v for gid, (v, _) in fits.items()}, weights, profile)
        rows.append((profile, fits, score))
    rows.sort(key=lambda r: (-r[2], r[0].id))
    return rows[:size]


async def rank(goals: Sequence[Goal], profiles: Iterable[PersonProfile], *,
               events: Iterable[Event] = (), scorer: Scorer | None = None,
               shortlist_size: int = 50, llm_cap: int = 20, limit: int | None = None
               ) -> tuple[list[PersonMatch], list[str]]:
    by_event = {e.id: e for e in events}
    weights = _weights(goals)
    warnings: list[str] = []
    matches: list[PersonMatch] = []
    for index, (profile, fits, det_score) in enumerate(
            shortlist(profiles, goals, size=shortlist_size)):
        slots, slot_warnings = where_slots(profile, by_event)
        warnings += slot_warnings
        matched_topics = [t for _, (_, hits) in fits.items() for t in hits
                          if t in profile.person.topics]
        opener = deterministic_opener(profile, matched_topics, slots)
        reasons = _reasons(profile, goals, fits, slots)
        goal_scores = {gid: round(v, 3) for gid, (v, _) in fits.items()}
        score, used, match_warnings = det_score, "deterministic", []
        parts = breakdown({gid: v for gid, (v, _) in fits.items()}, weights, profile)
        if scorer is not None and index < llm_cap:
            try:
                llm = await scorer.score(profile, goals)
                clipped = {g.id: min(max(float(llm.goal_scores.get(g.id, 0.0)), 0.0), 1.0)
                           for g in goals}
                score, goal_scores, used = _combine(clipped, weights, profile), clipped, "llm"
                parts = breakdown(clipped, weights, profile)
                if llm.reason:
                    reasons = [llm.reason, *reasons]
                if llm.opener:
                    opener = llm.opener
            except Exception as exc:  # noqa: BLE001 - visible fallback, never silent
                match_warnings.append(f"llm scorer failed ({type(exc).__name__}); "
                                      "deterministic score kept")
        person = profile.to_person()
        matches.append(PersonMatch(
            person=person, score=score, reasons=reasons, goal_scores=goal_scores,
            where=slots, opener=opener, presence_status=presence_status(profile),
            confidence=person.identity_confidence, scorer=used, warnings=match_warnings,
            score_breakdown=parts, grade=grade_for(score),
        ))
    matches.sort(key=lambda m: (-m.score, m.person.id))
    return (matches[:limit] if limit else matches), warnings


def apply_graph_adjustments(matches: Sequence[PersonMatch],
                            adjustments: Mapping[str, GraphAdjustment | Sequence[GraphAdjustment]]
                            ) -> list[PersonMatch]:
    """Pure: return re-scored, re-sorted copies; input matches are not mutated."""
    out = []
    for match in matches:
        raw = adjustments.get(match.person.id)
        items = [raw] if isinstance(raw, GraphAdjustment) else list(raw or [])
        if not items:
            out.append(match.model_copy())
            continue
        score = round(min(max(match.score + sum(a.delta for a in items), 0.0), 100.0), 2)
        reasons = [*match.reasons, *(f"graph {a.delta:+.1f}: {a.reason}" for a in items)]
        update: dict[str, object] = {"score": score, "reasons": reasons, "grade": grade_for(score)}
        if match.score_breakdown is not None:  # the clamped delta lands in "graph"
            parts = match.score_breakdown
            update["score_breakdown"] = parts.model_copy(update={"graph": round(
                parts.graph + score - parts.total(), 2)})
        out.append(match.model_copy(update=update))
    out.sort(key=lambda m: (-m.score, m.person.id))
    return out


async def run(goals: Sequence[Goal], candidates: Iterable[PersonProfile], *,
              events: Iterable[Event] = (), scorer: Scorer | None = None,
              limit: int | None = 10) -> RankingResult:
    """Rank candidates; source mode is inherited from the candidates' evidence."""
    candidates = list(candidates)
    matches, warnings = await rank(goals, candidates, events=events, scorer=scorer,
                                   limit=limit)
    modes = [e.source_mode for c in candidates for e in c.person.evidence]
    if not candidates:
        status: RunStatus = "failed"
        warnings.append("no candidates supplied")
    elif any(m.warnings for m in matches):
        status = "degraded"
    else:
        status = "ok"
    used = "llm" if any(m.scorer == "llm" for m in matches) else "deterministic"
    return RankingResult(
        matches=matches, source_mode=combine_modes(modes), status=status,
        shortlisted=len(shortlist(candidates, goals)), considered=len(candidates),
        scorer=used, warnings=warnings,
    )
