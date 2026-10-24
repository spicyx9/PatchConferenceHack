"""`Agent` adapter: ranks `AgentContext.people` and returns networking opportunities.

Profiles are rebuilt from core `Person` only: presence is confirmed solely for
`confirmed_speaker` / `confirmed_organizer` on their `event_ids`; any other participation
stays unknown. Opportunity.presence mirrors that, never upgraded.
"""

from __future__ import annotations

from collections.abc import Iterable

from conferge.core.schemas import AgentContext, AgentResult, Opportunity, Person
from conferge.people.match import Scorer, rank
from conferge.people.models import Presence, PersonProfile

_PARTICIPATION_KIND = {"confirmed_speaker": "speaker", "confirmed_organizer": "host"}


def profiles_from_people(people: Iterable[Person]) -> list[PersonProfile]:
    profiles = []
    for person in people:
        kind = _PARTICIPATION_KIND.get(person.participation)
        evidence = person.evidence[0] if person.evidence else None
        presences = []
        if kind and evidence is not None:
            presences = [Presence(event_id=e, kind=kind, status="confirmed", evidence=evidence)
                         for e in person.event_ids]
        profiles.append(PersonProfile(person=person, presences=presences,
                                      merged_from=[person.id]))
    return profiles


class PeopleAgent:
    """Implements conferge.core.contracts.Agent; offline by default (no scorer)."""

    name = "people"

    def __init__(self, scorer: Scorer | None = None, *, limit: int = 10) -> None:
        self.scorer = scorer
        self.limit = limit

    async def run(self, ctx: AgentContext) -> AgentResult:
        if not ctx.goals:
            return AgentResult(agent=self.name, source_mode=ctx.data_mode, status="failed",
                               errors=["no goals supplied"])
        if not ctx.people:
            return AgentResult(agent=self.name, source_mode=ctx.data_mode, status="failed",
                               errors=["no people in context"])
        profiles = profiles_from_people(ctx.people)
        matches, warnings = await rank(ctx.goals, profiles, events=ctx.events,
                                       scorer=self.scorer, limit=self.limit)
        opportunities = []
        for m in matches:
            first = m.where[0] if m.where else None
            where = None
            if first is not None:
                when = first.start_at.isoformat() if first.start_at else "time unknown"
                place = ", ".join(x for x in (first.venue, first.room) if x) or "venue unknown"
                where = f"{first.title} ({when}, {place})"
            goal_ids = [gid for gid, v in m.goal_scores.items() if v > 0]
            opportunities.append(Opportunity(
                id=f"opp:people:{m.person.id}",
                title=f"Meet {m.person.name}",
                goal_ids=goal_ids,
                event_id=first.event_id if first else None,
                person_ids=[m.person.id],
                company_ids=[m.person.company_id] if m.person.company_id else [],
                score=m.score,
                rationale="; ".join(m.reasons),
                where=where,
                opener=m.opener,
                presence=m.presence_status,
                evidence=list(m.person.evidence),
                warnings=m.warnings,
            ))
        warns = warnings + [w for m in matches for w in m.warnings]
        return AgentResult(
            agent=self.name, source_mode=ctx.data_mode,
            status="degraded" if warns else "ok",
            opportunities=opportunities,
            decisions=[{"person_id": m.person.id, "score": m.score, "scorer": m.scorer,
                        "presence": m.presence_status} for m in matches],
            explanations=[f"{m.person.name}: {m.reasons[0]}" for m in matches if m.reasons],
            errors=warns,
        )
