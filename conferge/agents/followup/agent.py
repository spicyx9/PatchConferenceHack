"""``Agent.run`` adaptor: one follow-up draft per person the user has MET.

Met people and their notes come from ``ctx.constraints``:
``met_person_ids`` (list) and ``met_notes`` (dict person_id -> note), the same
keys the planner reads for memory. Drafts are returned as decisions of type
``followup_draft``; nothing is sent.
"""

from __future__ import annotations

from datetime import datetime

from conferge.agents.followup.draft import FollowUpDraft, draft_followup
from conferge.core.schemas import AgentContext, AgentResult, Goal, Person


def best_goal(person: Person, goals: list[Goal]) -> Goal | None:
    """Goal with the highest weighted role/topic match, None when nothing matches."""
    scored = []
    for goal in goals:
        role = 1.0 if set(person.roles) & set(goal.target_roles) else 0.0
        topic = 0.25 if set(person.topics) & set(goal.topics) else 0.0
        match = min(role + topic, 1.0) if role else topic
        if match > 0:
            scored.append((goal.priority * match, goal))
    if not scored:
        return None
    return max(scored, key=lambda s: (s[0], s[1].id))[1]


def drafts_for_context(ctx: AgentContext, met_at: datetime | None = None) -> list[FollowUpDraft]:
    met_ids = [str(i) for i in ctx.constraints.get("met_person_ids", [])]
    notes = {str(k): str(v) for k, v in (ctx.constraints.get("met_notes") or {}).items()}
    people = {p.id: p for p in ctx.people}
    events = {e.id: e for e in ctx.events}
    out: list[FollowUpDraft] = []
    for pid in met_ids:
        person = people.get(pid)
        if person is None:
            continue
        event = next((events[e] for e in person.event_ids if e in events), None)
        out.append(
            draft_followup(
                person,
                conference=ctx.conference,
                goal=best_goal(person, ctx.goals),
                event=event,
                note=notes.get(pid),
                met_at=met_at,
            )
        )
    return out


class FollowUpAgent:
    name = "followup"

    async def run(self, ctx: AgentContext) -> AgentResult:
        drafts = drafts_for_context(ctx)
        errors: list[str] = []
        if not drafts:
            errors.append("no met person in context: nothing to follow up")
        return AgentResult(
            agent=self.name,
            source_mode=ctx.data_mode,
            status="ok" if drafts else "degraded",
            decisions=[{"type": "followup_draft", **d.model_dump(mode="json")} for d in drafts],
            explanations=[f"{len(drafts)} draft(s) proposed, none sent"],
            errors=errors,
        )


_DEFAULT = FollowUpAgent()


async def run(ctx: AgentContext) -> AgentResult:
    return await _DEFAULT.run(ctx)
