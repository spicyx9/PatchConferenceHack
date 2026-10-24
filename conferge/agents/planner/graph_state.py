"""Planner side of the shared agent state: the plan is published to FalkorDB.

Other agents (anti-FOMO, replanner) read it back from the graph, never from this process.
"""

from __future__ import annotations

from typing import Any

from conferge.core.store import GraphStore
from conferge.graph import agent_state

WRITER = "planner"


def plan_items(plan: dict[str, Any], attended: set[str]) -> list[dict[str, Any]]:
    """``(event_id, score, state)`` of a plan view (``{"days": [{"items": [...]}]}``)."""
    return [
        {"event_id": i["event_id"], "score": i.get("score"),
         "state": "locked" if i["event_id"] in attended or i.get("attended") else "tentative"}
        for d in plan.get("days", []) for i in d.get("items", [])
    ]


def publish_plan(store: GraphStore, user_id: str, plan: dict[str, Any], attended: set[str],
                 *, written_by: str = WRITER) -> dict[str, Any]:
    return agent_state.write_plan(store, user_id, plan_items(plan, attended), written_by=written_by)
