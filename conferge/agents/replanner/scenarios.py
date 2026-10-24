"""Three deterministic replanning demo scenarios over ``fixtures/antifomo.json``.

Exposed to the API (window 12) as ``list_scenarios()`` and ``run_scenario(id)``.
Every output is labelled ``source_mode=fixture``: the events are synthetic.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from conferge.agents.antifomo.conflicts import verdicts
from conferge.agents.antifomo.fixture import PlanningFixture, load_fixture, resolve_event
from conferge.agents.antifomo.models import Constraints
from conferge.agents.antifomo.optimizer import explain, optimize
from conferge.agents.replanner.events import Change, PlanningState, apply_change, diff, replan
from conferge.core.store import GraphStore

FIXTURE_LABEL = "fixture: synthetic events and people, simulated change; not live data"


def state_from_fixture(fx: PlanningFixture, constraints: Constraints | None = None
                       ) -> PlanningState:
    return PlanningState(
        conference_id=fx.conference.id, events=fx.events, people=fx.people, goals=fx.goals,
        constraints=constraints or Constraints(timezone=fx.conference.timezone),
    )


def list_scenarios(path: Path | None = None) -> list[dict[str, Any]]:
    fx = load_fixture(path)
    return [{"id": s["id"], "title": s["title"], "change_type": s["change"]["type"],
             "source_mode": "fixture"} for s in fx.scenarios]


def _change(raw: dict[str, Any], fx: PlanningFixture) -> Change:
    data = dict(raw)
    if isinstance(data.get("event"), dict):
        data["event"] = resolve_event(data["event"], fx.venues, fx.collected_at.isoformat())
    data.setdefault("source_mode", "fixture")
    data.setdefault("observed_at", fx.collected_at)
    return Change.model_validate(data)


def run_scenario(scenario_id: str, path: Path | None = None, store: GraphStore | None = None
                 ) -> dict[str, Any]:
    fx = load_fixture(path)
    spec = next((s for s in fx.scenarios if s["id"] == scenario_id), None)
    if spec is None:
        known = ", ".join(s["id"] for s in fx.scenarios)
        raise KeyError(f"unknown scenario {scenario_id!r}; known: {known}")
    state = state_from_fixture(fx)
    before = optimize(state.candidates(), state.constraints)
    change = _change(spec["change"], fx)
    result = apply_change(state, change, store)
    after = replan(before, result.state)
    delta = diff(before, after)
    after_cands = result.state.candidates()
    return {
        "id": scenario_id,
        "title": spec["title"],
        "source_mode": "fixture",
        "label": FIXTURE_LABEL,
        "change": change.model_dump(mode="json", exclude_none=True),
        "effects": result.effects,
        "graph_writes": result.graph_writes,
        "errors": result.errors,
        "before": before.model_dump(mode="json"),
        "after": after.model_dump(mode="json"),
        "diff": delta.model_dump(mode="json"),
        "explanations": explain(after),
        "verdicts_after": [v.model_dump(mode="json")
                           for v in verdicts(after_cands, result.state.people,
                                             result.state.constraints)],
    }
