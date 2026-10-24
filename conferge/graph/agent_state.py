"""Shared agent state in FalkorDB: the plan, the anti-FOMO skips and the plan changes.

Agents coordinate through the graph, not through Python objects:

    (User)-[:PLANS {state, score, plan_version, versions, written_by, at_ms}]->(Event)
    (User)-[:SKIPS {state, reason, detail, written_by, at_ms}]->(Event)
    (Change {label, scenario_id, from_version, to_version, written_by, at_ms})-[:AFFECTS]->(Event)

``state`` is ``locked`` (user confirmed) or ``tentative`` for a planned event, and
``invalidated`` once a later plan drops it. Replanning never deletes (``POST /reset``, a hard
demo reset, is the one exception: it wipes the demo user's state). An invalidated
``PLANS`` edge keeps the ``plan_version`` it last belonged to, and ``versions`` lists every
plan version that contained the event. Writes go through ``GraphStore`` MERGE only and are
idempotent: re-writing the same plan or the same skips changes nothing, not even ``at_ms``.
Reads use ``GRAPH.RO_QUERY`` when the client has it.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Literal

from conferge.core.store import GraphStore
from conferge.graph.queries import literal_cypher, run_read

PlanState = Literal["locked", "tentative"]
AGENTS = ("planner", "antifomo", "replanner")

Q_PLANS = (
    "MATCH (u:User {id: $user_id})-[r:PLANS]->(e:Event) "
    "RETURN e.id, r.state, r.score, r.plan_version, r.versions, r.written_by, r.at_ms"
)
Q_SKIPS = (
    "MATCH (u:User {id: $user_id})-[r:SKIPS]->(e:Event) "
    "RETURN e.id, r.state, r.reason, r.detail, r.written_by, r.at_ms"
)
Q_CHANGES = (
    "MATCH (c:Change {user_id: $user_id}) OPTIONAL MATCH (c)-[:AFFECTS]->(e:Event) "
    "RETURN c.id, c.label, c.scenario_id, c.from_version, c.to_version, c.written_by, c.at_ms, "
    "collect(e.id) ORDER BY c.at_ms"
)
Q_ACTIVITY = (
    "MATCH (u:User {id: $user_id})-[r:PLANS|SKIPS]->(:Event) "
    "RETURN r.written_by AS agent, count(r) AS writes, max(r.at_ms) AS last "
    "UNION ALL MATCH (c:Change {user_id: $user_id}) "
    "RETURN c.written_by AS agent, count(c) AS writes, max(c.at_ms) AS last"
)
# For the UI: paste into FalkorDB Browser to see what the agents wrote for the user.
Q_SHOW_STATE = (
    "MATCH (u:User {id: $user_id})-[r:PLANS|SKIPS]->(e:Event) "
    "RETURN u, r, e ORDER BY type(r), r.state, r.score DESC"
)


def now_ms() -> int:
    return int(time.time() * 1000)


def _provenance(at_ms: int) -> dict[str, Any]:
    """Edge provenance required by conferge/graph/schema.py: the agent decided it at ``at_ms``."""
    return {"source": "agent", "source_mode": "live", "confidence": 1.0, "verification": "agent_decision",
            "observed_at": datetime.fromtimestamp(at_ms / 1000, tz=timezone.utc).isoformat()}


def ensure_user(store: GraphStore, user_id: str) -> None:
    store.merge_node("User", user_id, {"name": user_id, "source": "user", "source_mode": "live"})


def read_plan_edges(store: GraphStore, user_id: str) -> list[dict[str, Any]]:
    """Every ``PLANS`` edge of the user, invalidated ones included."""
    keys = ("event_id", "state", "score", "plan_version", "versions", "written_by", "at_ms")
    return [dict(zip(keys, row, strict=True)) for row in run_read(store, Q_PLANS, {"user_id": user_id})]


def read_plan(store: GraphStore, user_id: str) -> dict[str, Any]:
    """The current plan: ``{"plan_version", "items": [{event_id, state, score, written_by, at_ms}]}``.

    ``plan_version`` is 0 when no plan was ever written. Items are sorted by event id.
    """
    edges = read_plan_edges(store, user_id)
    version = max((e["plan_version"] or 0 for e in edges), default=0)
    items = sorted(
        ({k: e[k] for k in ("event_id", "state", "score", "written_by", "at_ms")}
         for e in edges if e["state"] != "invalidated" and e["plan_version"] == version),
        key=lambda i: i["event_id"],
    )
    return {"plan_version": version, "items": items}


def write_plan(store: GraphStore, user_id: str, items: list[dict[str, Any]], *,
               written_by: str, at_ms: int | None = None) -> dict[str, Any]:
    """Write ``items`` (``event_id``, ``score``, ``state``) as the user's plan.

    Same events, states and scores as the current plan: nothing is written and the current
    version is returned. Otherwise the version is incremented, dropped events become
    ``invalidated`` (keeping their last ``plan_version``) and kept or new events get the new
    version. Returns ``{"plan_version", "changed", "invalidated": [event ids]}``.
    """
    edges = {e["event_id"]: e for e in read_plan_edges(store, user_id)}
    current = read_plan(store, user_id)
    wanted = {i["event_id"]: i for i in items}
    same = (
        {i["event_id"]: (i["state"], _score(i["score"])) for i in current["items"]}
        == {k: (v["state"], _score(v.get("score"))) for k, v in wanted.items()}
    )
    if current["plan_version"] and same:
        return {"plan_version": current["plan_version"], "changed": False, "invalidated": []}
    version = current["plan_version"] + 1
    at = at_ms if at_ms is not None else now_ms()
    ensure_user(store, user_id)
    dropped = [i["event_id"] for i in current["items"] if i["event_id"] not in wanted]
    for event_id in dropped:
        store.merge_edge("User", user_id, "PLANS", "Event", event_id, {
            "state": "invalidated", "invalidated_by": written_by, "invalidated_at_ms": at,
        })
    for event_id, item in wanted.items():
        versions = list(edges.get(event_id, {}).get("versions") or [])
        store.merge_edge("User", user_id, "PLANS", "Event", event_id, {
            "state": item["state"], "score": _score(item.get("score")), "plan_version": version,
            "versions": [*versions, version], "written_by": written_by, "at_ms": at, **_provenance(at),
        })
    return {"plan_version": version, "changed": True, "invalidated": dropped}


def read_skips(store: GraphStore, user_id: str, *, active_only: bool = True) -> list[dict[str, Any]]:
    keys = ("event_id", "state", "reason", "detail", "written_by", "at_ms")
    rows = [dict(zip(keys, row, strict=True)) for row in run_read(store, Q_SKIPS, {"user_id": user_id})]
    rows = [r for r in rows if r["state"] != "invalidated"] if active_only else rows
    return sorted(rows, key=lambda r: r["event_id"])


def write_skips(store: GraphStore, user_id: str, skips: list[dict[str, Any]], *,
                written_by: str, at_ms: int | None = None) -> dict[str, Any]:
    """Make ``skips`` (``event_id``, ``reason``, optional ``detail``) the active skips.

    Unchanged skips are not rewritten; skips no longer given become ``invalidated``.
    Returns ``{"written": n, "invalidated": [event ids]}``.
    """
    current = {s["event_id"]: s for s in read_skips(store, user_id)}
    wanted = {s["event_id"]: s for s in skips}
    at = at_ms if at_ms is not None else now_ms()
    written, invalidated = 0, []
    if wanted or current:
        ensure_user(store, user_id)
    for event_id, skip in wanted.items():
        old = current.get(event_id)
        if old and old["reason"] == skip["reason"] and old["detail"] == skip.get("detail"):
            continue
        store.merge_edge("User", user_id, "SKIPS", "Event", event_id, {
            "state": "active", "reason": skip["reason"], "detail": skip.get("detail"),
            "written_by": written_by, "at_ms": at, **_provenance(at),
        })
        written += 1
    for event_id in current.keys() - wanted.keys():
        store.merge_edge("User", user_id, "SKIPS", "Event", event_id, {
            "state": "invalidated", "invalidated_by": written_by, "invalidated_at_ms": at,
        })
        invalidated.append(event_id)
    return {"written": written, "invalidated": sorted(invalidated)}


def write_change(store: GraphStore, user_id: str, *, label: str, scenario_id: str | None,
                 event_ids: list[str], from_version: int, written_by: str,
                 overrides_skips: list[str] | None = None, at_ms: int | None = None) -> str:
    """Record a plan change and the events it affects; returns the ``Change`` id."""
    at = at_ms if at_ms is not None else now_ms()
    change_id = f"change:{user_id}:{at}"
    store.merge_node("Change", change_id, {
        "user_id": user_id, "label": label, "scenario_id": scenario_id,
        "from_version": from_version, "written_by": written_by, "at_ms": at,
        "overrides_skips": overrides_skips or [], "source": "agent", "source_mode": "live",
    })
    for event_id in event_ids:
        store.merge_edge("Change", change_id, "AFFECTS", "Event", event_id, {
            "written_by": written_by, "at_ms": at, **_provenance(at),
        })
    return change_id


def set_change_version(store: GraphStore, change_id: str, to_version: int) -> None:
    store.merge_node("Change", change_id, {"to_version": to_version})


def read_changes(store: GraphStore, user_id: str) -> list[dict[str, Any]]:
    keys = ("id", "label", "scenario_id", "from_version", "to_version", "written_by", "at_ms", "event_ids")
    return [dict(zip(keys, row, strict=True)) for row in run_read(store, Q_CHANGES, {"user_id": user_id})]


def agent_activity(store: GraphStore, user_id: str) -> list[dict[str, Any]]:
    """Per agent: graph facts it wrote for the user (PLANS, SKIPS, Change) and its last ``at_ms``."""
    counts: dict[str, list[int | None]] = {a: [0, None] for a in AGENTS}
    for agent, n, last in run_read(store, Q_ACTIVITY, {"user_id": user_id}):
        if agent is None:
            continue
        entry = counts.setdefault(agent, [0, None])
        entry[0] = int(entry[0] or 0) + int(n or 0)
        if last is not None:
            entry[1] = max(int(last), entry[1] or 0)
    return [{"agent": a, "writes": c[0], "last_at_ms": c[1]} for a, c in counts.items()]


def state_cypher(user_id: str) -> str:
    """Copyable Cypher showing the user's PLANS and SKIPS (display only)."""
    return literal_cypher(Q_SHOW_STATE, {"user_id": user_id})


def _score(value: Any) -> float | None:
    return round(float(value), 2) if value is not None else None
