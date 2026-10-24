"""``Agent.run`` adaptor for live replanning.

``ctx.constraints`` keys read here:
* ``scenario_id``: run a fixture demo scenario (output labelled fixture);
* ``change``: a ``Change`` payload applied to the context events;
* ``original_plan``: event ids of the agenda to preserve (default: the optimal
  agenda computed from the context before the change).
"""

from __future__ import annotations

from typing import Any

from conferge.agents.antifomo.agent import constraints_from_context, plan_opportunities
from conferge.agents.antifomo.optimizer import explain, optimize
from conferge.agents.replanner.events import Change, PlanningState, apply_change, diff, replan
from conferge.agents.replanner.scenarios import run_scenario
from conferge.core.schemas import AgentContext, AgentResult


class ReplannerAgent:
    name = "replanner"

    async def run(self, ctx: AgentContext) -> AgentResult:
        scenario_id = ctx.constraints.get("scenario_id")
        if scenario_id:
            return self._scenario(str(scenario_id))
        raw_change = ctx.constraints.get("change")
        if not raw_change:
            return AgentResult(agent=self.name, source_mode=ctx.data_mode, status="failed",
                               errors=["no change or scenario_id in ctx.constraints"])
        try:
            change = Change.model_validate(raw_change)
            state = PlanningState(
                conference_id=ctx.conference.id, events=ctx.events, people=ctx.people,
                goals=ctx.goals, opportunities=ctx.opportunities,
                constraints=constraints_from_context(ctx),
            )
            original_ids = ctx.constraints.get("original_plan")
            before = optimize(state.candidates(), state.constraints,
                              original=original_ids if original_ids else None)
            result = apply_change(state, change)
        except ValueError as exc:
            return AgentResult(agent=self.name, source_mode=ctx.data_mode, status="failed",
                               errors=[f"invalid change: {exc}"])
        after = replan(before, result.state)
        delta = diff(before, after)
        cands = {c.id: c.goal_ids for c in result.state.candidates()}
        decisions: list[dict[str, Any]] = [
            {"type": "diff", **delta.model_dump(mode="json")},
            {"type": "effects", "effects": result.effects},
        ] + after.as_decisions()
        return AgentResult(
            agent=self.name, source_mode=ctx.data_mode,
            status="degraded" if result.errors else "ok",
            opportunities=plan_opportunities(after, cands), decisions=decisions,
            explanations=delta.reasons + explain(after), errors=result.errors,
        )

    def _scenario(self, scenario_id: str) -> AgentResult:
        try:
            out = run_scenario(scenario_id)
        except (KeyError, FileNotFoundError) as exc:
            return AgentResult(agent=self.name, source_mode="fixture", status="failed",
                               errors=[str(exc)])
        return AgentResult(
            agent=self.name, source_mode="fixture", status="ok",
            decisions=[{"type": "scenario", **out}],
            explanations=[out["label"], *out["diff"]["reasons"]],
        )


async def run(ctx: AgentContext) -> AgentResult:
    return await ReplannerAgent().run(ctx)
