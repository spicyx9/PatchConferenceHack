"""``Agent.run`` adaptor: AgentContext -> plan + anti-FOMO verdicts."""

from __future__ import annotations

from typing import Any

from conferge.agents.antifomo.conflicts import verdicts
from conferge.agents.antifomo.models import Constraints, Plan
from conferge.agents.antifomo.optimizer import explain, optimize
from conferge.agents.antifomo.scoring import build_candidates
from conferge.core.schemas import AgentContext, AgentResult, Opportunity

_CONSTRAINT_KEYS = set(Constraints.model_fields)


def constraints_from_context(ctx: AgentContext) -> Constraints:
    """Planning constraints live in ``ctx.constraints``; unknown keys are ignored.

    ``budget_usd`` here is the *events* budget. ``ctx.budget_usd`` is the whole
    trip budget (flights, lodging) and is deliberately not used for events.
    """
    raw: dict[str, Any] = {k: v for k, v in ctx.constraints.items() if k in _CONSTRAINT_KEYS}
    raw.setdefault("timezone", ctx.conference.timezone)
    return Constraints.model_validate(raw)


def plan_opportunities(plan: Plan, goal_ids_by_event: dict[str, list[str]]) -> list[Opportunity]:
    return [
        Opportunity(
            id=f"opp-antifomo-{item.event_id}",
            title=item.title,
            goal_ids=goal_ids_by_event.get(item.event_id, []),
            event_id=item.event_id,
            person_ids=item.targets_confirmed + item.targets_probable,
            score=item.utility,
            rationale="; ".join(item.reasons) or "selected by the agenda optimizer",
            where=item.venue_name,
            presence="confirmed" if item.targets_confirmed else
            "probable" if item.targets_probable else "unknown",
            warnings=item.warnings,
        )
        for item in plan.items
    ]


class AntiFomoAgent:
    name = "antifomo"

    async def run(self, ctx: AgentContext) -> AgentResult:
        constraints = constraints_from_context(ctx)
        cands = build_candidates(ctx.events, ctx.goals, ctx.people, ctx.opportunities)
        plan = optimize(cands, constraints)
        found = verdicts(cands, ctx.people, constraints)
        errors: list[str] = []
        if not ctx.events:
            errors.append("no events in context: nothing to plan")
        status = "ok" if plan.items else "degraded"
        if not plan.items and ctx.events:
            errors.append("no schedulable event (times unknown or all filtered)")
        decisions = plan.as_decisions() + [
            {"type": "verdict", **v.model_dump(mode="json")} for v in found
        ]
        return AgentResult(
            agent=self.name,
            source_mode=ctx.data_mode,
            status=status,
            opportunities=plan_opportunities(plan, {c.id: c.goal_ids for c in cands}),
            decisions=decisions,
            explanations=explain(plan) + [v.text for v in found],
            errors=errors,
        )


async def run(ctx: AgentContext) -> AgentResult:
    return await AntiFomoAgent().run(ctx)
