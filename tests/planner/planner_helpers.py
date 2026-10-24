"""Shared offline helpers for the w09 planner tests (fixtures/planner.json only)."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from conferge.agents.planner import PlannerAgent
from conferge.core.schemas import AgentContext, AgentResult

FIXTURE_PATH = Path(__file__).resolve().parents[2] / "fixtures" / "planner.json"

FRENCH_DEMO = (
    "Fondateur d'un outil dev IA, je vais à GitHub Universe pour rencontrer des "
    "investisseurs seed, des fondateurs d'agents IA et des PM Copilot."
)


def load_fixture() -> dict[str, Any]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def raw_context(**constraints: Any) -> dict[str, Any]:
    """Deep copy of the fixture context with goal_text plus extra constraints."""
    fx = load_fixture()
    raw = copy.deepcopy(fx["context"])
    raw["constraints"] = {"goal_text": fx["goal_text"], **constraints}
    return raw


def make_ctx(raw: dict[str, Any] | None = None, **constraints: Any) -> AgentContext:
    return AgentContext.model_validate(raw if raw is not None else raw_context(**constraints))


async def run_planner(ctx: AgentContext, **kwargs: Any) -> AgentResult:
    kwargs.setdefault("people_limit", None)
    return await PlannerAgent(**kwargs).run(ctx)


def plan_of(result: AgentResult) -> dict[str, Any]:
    plans = [d for d in result.decisions if d.get("type") == "plan"]
    assert len(plans) == 1, result.decisions
    return plans[0]


def planned_ids(result: AgentResult) -> list[str]:
    return [item["id"] for day in plan_of(result)["days"] for item in day["items"]]


def rejected_map(result: AgentResult) -> dict[str, str]:
    return {r["id"]: r["reason"] for r in plan_of(result)["rejected"]}


def ranking(result: AgentResult) -> list[str]:
    return [o.person_ids[0] for o in result.opportunities]
