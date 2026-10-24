"""Replanner side of the shared agent state.

Reads the current plan (``PLANS``) and the active skips (``SKIPS``) from FalkorDB, records
the change as a ``Change`` node that ``AFFECTS`` the changed events, then writes the new plan
with an incremented ``plan_version``. When the new plan puts back an event the anti-FOMO
agent had skipped, the ``Change`` node says so (``overrides_skips``) instead of hiding it.
"""

from __future__ import annotations

from typing import Any

from conferge.agents.planner.graph_state import plan_items
from conferge.core.store import GraphStore
from conferge.graph import agent_state

WRITER = "replanner"


def publish_replan(store: GraphStore, user_id: str, *, label: str, scenario_id: str | None,
                   changed: list[str], new_plan: dict[str, Any], attended: set[str]) -> dict[str, Any]:
    before = agent_state.read_plan(store, user_id)
    skipped = {s["event_id"] for s in agent_state.read_skips(store, user_id)}
    items = plan_items(new_plan, attended)
    overrides = sorted(skipped & {i["event_id"] for i in items})
    change_id = agent_state.write_change(
        store, user_id, label=label, scenario_id=scenario_id, event_ids=changed,
        from_version=before["plan_version"], written_by=WRITER, overrides_skips=overrides)
    written = agent_state.write_plan(store, user_id, items, written_by=WRITER)
    agent_state.set_change_version(store, change_id, written["plan_version"])
    return {"change_id": change_id, "from_version": before["plan_version"],
            "overrides_skips": overrides, **written}
