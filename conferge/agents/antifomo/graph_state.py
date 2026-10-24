"""Anti-FOMO side of the shared agent state: reads the plan from FalkorDB, writes its skips."""

from __future__ import annotations

from typing import Any

from conferge.core.store import GraphStore
from conferge.graph import agent_state

WRITER = "antifomo"


def planned_from_graph(store: GraphStore, user_id: str) -> tuple[set[str], int]:
    """Event ids of the current plan as written in the graph, and its ``plan_version``."""
    plan = agent_state.read_plan(store, user_id)
    return {i["event_id"] for i in plan["items"]}, plan["plan_version"]


def publish_skips(store: GraphStore, user_id: str, skips: list[dict[str, Any]]) -> dict[str, Any]:
    """Each skip (``event_id``, ``category``, ``reason``) becomes a ``SKIPS`` edge."""
    return agent_state.write_skips(store, user_id, [
        {"event_id": s["event_id"], "reason": s["category"], "detail": s.get("reason")} for s in skips
    ], written_by=WRITER)
