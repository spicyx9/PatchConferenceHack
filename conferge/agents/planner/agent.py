"""Reverse planner agent: ``async run(AgentContext) -> AgentResult``.

Pipeline: goals (context, else parsed from ``constraints["goal_text"]``, else
visible defaults) -> memory exclusions (context, in-process book, optional
graph) -> person ranking (networking) -> event scoring -> per-day plan.

Output contract:
* ``opportunities``: ranked people (who, why, where, how, presence, evidence);
* ``decisions``: ``{"type": "plan", "days", "rejected", "warnings"}`` first,
  then one ``{"type": "event_score", ...}`` per event and any
  ``{"type": "excluded_person", ...}``;
* ``explanations``: short human summary, including graph and data-mode status.
"""

from __future__ import annotations

from typing import Any

from conferge.agents.networking.graph_reader import GraphReader
from conferge.agents.networking.memory import MemoryBook
from conferge.agents.networking.recommend import recommend
from conferge.agents.planner.candidates import World, event_candidate
from conferge.agents.planner.goals import parse_goals
from conferge.agents.planner.plan import PlanCandidate, PlanConstraints, optimize
from conferge.agents.planner.scoring import DEFAULT_WEIGHTS, Weights, score_candidate
from conferge.core.schemas import AgentContext, AgentResult, DataMode, Event, SourceEvidence

AGENT_NAME = "planner-w09"
MIN_SIDE_EVENT_RELATION = 0.5


def evidence_mode(evidence: list[SourceEvidence], declared: DataMode) -> DataMode:
    modes = {e.source_mode for e in evidence}
    if not modes:
        return declared
    return next(iter(modes)) if len(modes) == 1 else "mixed"  # type: ignore[return-value]


def plannable(event: Event) -> str | None:
    """Reason the event is not a plan candidate, or None."""
    if event.conference_relation in {"official", "confirmed_side_event"}:
        return None
    if event.conference_relation == "candidate":
        if (event.relation_score or 0.0) >= MIN_SIDE_EVENT_RELATION:
            return None
        return f"candidate side event with relation_score {event.relation_score} < {MIN_SIDE_EVENT_RELATION}"
    return f"conference relation {event.conference_relation}"


class PlannerAgent:
    name = AGENT_NAME

    def __init__(self, graph: Any | None = None, memory: MemoryBook | None = None,
                 weights: Weights = DEFAULT_WEIGHTS, people_limit: int | None = 10,
                 include_plan: bool = True) -> None:
        self.graph = graph
        self.memory = memory or MemoryBook()
        self.weights = weights
        self.people_limit = people_limit
        self.include_plan = include_plan

    async def run(self, ctx: AgentContext) -> AgentResult:
        errors: list[str] = []
        explanations: list[str] = []
        degraded = False

        goals = ctx.goals
        if not goals:
            goals = parse_goals(ctx.constraints.get("goal_text"))
            ctx = ctx.model_copy(update={"goals": goals})
            source = "default" if goals and goals[0].tags[0].startswith("default") else "parsed"
            explanations.append(f"no goals in context: {source} goals used "
                                f"({', '.join(g.id for g in goals)})")
            degraded = degraded or source == "default"

        excluded = {str(i) for key in ("met_person_ids", "contacted_person_ids")
                    for i in ctx.constraints.get(key, []) or []}
        excluded |= self.memory.excluded(ctx.user_id)
        hints = {}
        if self.graph is None:
            explanations.append("graph not connected: ranking from AgentContext facts only")
        else:
            reader = GraphReader(self.graph)
            excluded |= reader.excluded_people(ctx.user_id)
            hints = reader.hints(ctx.user_id, goals)
            if reader.warnings:
                degraded = True
                errors.extend(reader.warnings)
            else:
                explanations.append(f"graph connected: {len(hints)} people have a goal path")

        people_by_id = {p.id: p for p in ctx.people}
        met_companies = {people_by_id[p].company_id for p in excluded
                         if p in people_by_id and people_by_id[p].company_id}
        world = World(ctx, met=excluded, met_companies=met_companies)  # type: ignore[arg-type]

        opportunities, person_decisions = recommend(
            world, weights=self.weights, graph_hints=hints, limit=self.people_limit)

        decisions: list[dict[str, Any]] = []
        plan_candidates: list[PlanCandidate] = []
        event_decisions: list[dict[str, Any]] = []
        not_plannable: list[dict[str, str]] = []
        for event in sorted(ctx.events, key=lambda e: e.id):
            cand = event_candidate(world, event)
            breakdown = score_candidate(cand, self.weights)
            reason = f"{breakdown.explanation}. Facts: " + " | ".join(cand.facts)
            event_decisions.append({
                "type": "event_score", "event_id": event.id, "title": event.title,
                "score": breakdown.score, "terms": breakdown.terms, "goal_ids": cand.goal_ids,
                "explanation": reason,
            })
            why_not = plannable(event)
            if why_not:
                not_plannable.append({"id": event.id, "reason": why_not})
            else:
                plan_candidates.append(PlanCandidate(event, breakdown.score, reason, cand.path))

        if self.include_plan:
            constraints, warnings = PlanConstraints.from_mapping(
                ctx.constraints, ctx.conference.timezone, ctx.budget_usd)
            errors.extend(warnings)
            degraded = degraded or bool(warnings)
            plan = await optimize(plan_candidates, constraints,
                                  original=ctx.constraints.get("original_event_ids"))
            plan["rejected"] = sorted(plan["rejected"] + not_plannable, key=lambda r: r["id"])
            decisions.append({"type": "plan", **plan})
            planned = sum(len(d["items"]) for d in plan["days"])
            explanations.append(f"plan: {planned} item(s) over {len(plan['days'])} day(s), "
                                f"{len(plan['rejected'])} rejected with reasons")
        decisions.extend(event_decisions)
        decisions.extend(person_decisions)

        evidence = [e for p in ctx.people for e in p.evidence] + [
            e for ev in ctx.events for e in ev.evidence]
        mode = evidence_mode(evidence, ctx.data_mode)
        if mode != ctx.data_mode and ctx.data_mode != "mixed":
            explanations.append(f"context declared {ctx.data_mode}, record evidence says {mode}; "
                                f"reporting {mode}")
        if mode in {"fixture", "mixed"}:
            explanations.append(f"source mode {mode}: fixture-backed records are not live claims")

        if not ctx.people and not ctx.events:
            errors.append("empty context: no people and no events to rank")
            degraded = True
        for opp in opportunities[:3]:
            explanations.append(f"{opp.title}: {opp.score} ({opp.presence}) {opp.where or ''}".strip())
        explanations.append("goals: " + ", ".join(f"{g.id}={g.priority}" for g in goals))

        return AgentResult(
            agent=self.name, source_mode=mode, status="degraded" if degraded else "ok",
            opportunities=opportunities, decisions=decisions,
            explanations=explanations, errors=errors,
        )


_DEFAULT = PlannerAgent()


async def run(ctx: AgentContext) -> AgentResult:
    """Module-level entry point discovered by the API (``conferge.api.providers``).

    Connected to FalkorDB by default (FALKORDB_HOST/PORT from the env or .env); without a
    graph it runs on AgentContext facts only and says so in its explanations.
    """
    from conferge.core.store import connect_graph_or_none

    store = connect_graph_or_none()
    agent = _DEFAULT if store is None else PlannerAgent(graph=store, memory=_DEFAULT.memory)
    return await agent.run(ctx)
