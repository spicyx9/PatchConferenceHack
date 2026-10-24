"""Shared agent state in the real FalkorDB: plan, skips, changes; restart and two processes.

Opt-in like the journey (``CONFERGE_E2E=1``, ``make e2e``), FalkorDB at FALKORDB_HOST:FALKORDB_PORT.
"""

from __future__ import annotations

import os
from typing import Any

import pytest

from conferge.agents.antifomo.graph_state import planned_from_graph, publish_skips
from conferge.agents.planner.graph_state import publish_plan
from conferge.agents.replanner.graph_state import publish_replan
from conferge.core.store import GraphStore
from conferge.graph import agent_state
from conferge.graph.queries import run_read
from test_full_journey import HOST, PORT, Api, _falkordb_up

pytestmark = pytest.mark.skipif(os.environ.get("CONFERGE_E2E") != "1",
                                reason="needs FalkorDB: set CONFERGE_E2E=1 (make e2e)")
USER = "demo-user"


@pytest.fixture()
def store() -> Any:
    if not _falkordb_up():
        pytest.fail(f"FalkorDB not reachable at {HOST}:{PORT}")
    from falkordb import FalkorDB

    graph = FalkorDB(host=HOST, port=PORT).select_graph("conferge_agent_state_test")
    try:
        graph.delete()
    except Exception:  # noqa: BLE001 - absent graph
        pass
    s = GraphStore(graph)
    for eid in ("e1", "e2", "e3", "e4"):
        s.merge_node("Event", eid, {"title": eid.upper()})
    yield s
    graph.delete()


def _plan(*ids: str) -> dict[str, Any]:
    return {"days": [{"day": "2026-10-28", "items": [{"event_id": i, "score": 10.0} for i in ids]}]}


def _edges(store: GraphStore) -> dict[str, dict[str, Any]]:
    return {e["event_id"]: e for e in agent_state.read_plan_edges(store, USER)}


def test_plan_write_is_idempotent(store: GraphStore) -> None:
    first = publish_plan(store, USER, _plan("e1", "e2"), attended={"e1"})
    assert first == {"plan_version": 1, "changed": True, "invalidated": []}
    at = {k: e["at_ms"] for k, e in _edges(store).items()}
    again = publish_plan(store, USER, _plan("e1", "e2"), attended={"e1"})
    assert again == {"plan_version": 1, "changed": False, "invalidated": []}
    assert {k: e["at_ms"] for k, e in _edges(store).items()} == at
    states = {i["event_id"]: i["state"] for i in agent_state.read_plan(store, USER)["items"]}
    assert states == {"e1": "locked", "e2": "tentative"}
    users = run_read(store, "MATCH (u:User {id: $id}) RETURN count(u)", {"id": USER})
    assert users == [[1]]


def test_new_plan_invalidates_old_edges_without_deleting(store: GraphStore) -> None:
    publish_plan(store, USER, _plan("e1", "e2"), attended=set())
    second = publish_plan(store, USER, _plan("e2", "e3"), attended=set())
    assert second["plan_version"] == 2 and second["invalidated"] == ["e1"]
    edges = _edges(store)
    assert edges["e1"]["state"] == "invalidated" and edges["e1"]["plan_version"] == 1
    assert edges["e1"]["versions"] == [1]
    assert edges["e2"]["versions"] == [1, 2] and edges["e3"]["versions"] == [2]
    current = agent_state.read_plan(store, USER)
    assert current["plan_version"] == 2
    assert [i["event_id"] for i in current["items"]] == ["e2", "e3"]


def test_antifomo_reads_plan_from_graph_and_writes_skips(store: GraphStore) -> None:
    publish_plan(store, USER, _plan("e1", "e2"), attended=set())
    planned, version = planned_from_graph(store, USER)
    assert planned == {"e1", "e2"} and version == 1
    skips = [{"event_id": "e3", "category": "time_conflict", "reason": "overlaps E1"},
             {"event_id": "e4", "category": "low_score", "reason": "score 0"}]
    assert publish_skips(store, USER, skips) == {"written": 2, "invalidated": []}
    assert publish_skips(store, USER, skips) == {"written": 0, "invalidated": []}
    assert publish_skips(store, USER, skips[:1]) == {"written": 0, "invalidated": ["e4"]}
    active = agent_state.read_skips(store, USER)
    assert [(s["event_id"], s["reason"], s["written_by"]) for s in active] == [("e3", "time_conflict", "antifomo")]
    assert len(agent_state.read_skips(store, USER, active_only=False)) == 2



def test_agent_edges_carry_the_graph_provenance_contract(store: GraphStore) -> None:
    publish_plan(store, USER, _plan("e1"), attended=set())
    publish_skips(store, USER, [{"event_id": "e2", "category": "low_score", "reason": "x"}])
    publish_replan(store, USER, label="c", scenario_id=None, changed=["e1"], new_plan=_plan("e3"), attended=set())
    rows = run_read(store, "MATCH ()-[r:PLANS|SKIPS|AFFECTS]->() "
                           "RETURN type(r), r.source, r.source_mode, r.confidence, r.observed_at, r.verification")
    assert rows and all(all(v is not None for v in row) for row in rows), rows


def test_replanner_reads_plans_and_skips_writes_change_and_new_version(store: GraphStore) -> None:
    publish_plan(store, USER, _plan("e1", "e2"), attended=set())
    publish_skips(store, USER, [{"event_id": "e3", "category": "low_score", "reason": "x"}])
    out = publish_replan(store, USER, label="E1 sold out", scenario_id="sold-out",
                         changed=["e1"], new_plan=_plan("e2", "e3"), attended=set())
    assert out["from_version"] == 1 and out["plan_version"] == 2
    assert out["invalidated"] == ["e1"] and out["overrides_skips"] == ["e3"]
    [change] = agent_state.read_changes(store, USER)
    assert change["event_ids"] == ["e1"] and change["from_version"] == 1 and change["to_version"] == 2
    assert change["written_by"] == "replanner"
    activity = {a["agent"]: a for a in agent_state.agent_activity(store, USER)}
    assert activity["planner"]["writes"] == 1  # e1, invalidated but kept, still the planner's
    assert activity["replanner"]["writes"] == 3  # e2, e3 re-planned + one Change
    assert activity["antifomo"]["writes"] == 1
    assert all(a["last_at_ms"] for a in activity.values())
    rows = run_read(store, agent_state.state_cypher(USER).replace(" RETURN u, r, e", " RETURN type(r), e.id")
                    .split(" ORDER BY")[0])
    assert sorted(map(tuple, rows)) == [("PLANS", "e1"), ("PLANS", "e2"), ("PLANS", "e3"), ("SKIPS", "e3")]


def test_plan_survives_api_restart_and_is_shared_by_two_processes() -> None:
    if not _falkordb_up():
        pytest.fail(f"FalkorDB not reachable at {HOST}:{PORT}")
    a, b = Api(), Api()
    a.start()
    try:
        a.call("POST", "/reset", {})
        a.call("GET", "/antifomo")
        scenarios = a.call("GET", "/scenarios")["items"]
        pick = next((s for s in scenarios if "sold" in s["id"].lower()), scenarios[0])
        sim = a.call("POST", "/simulate-change", {"scenario_id": pick["id"]})
        assert sim["plan_graph"]["plan_version"] >= 2, sim["plan_graph"]
        before = a.call("GET", "/agents/state")
        assert before["backend"] == "falkordb" and before["plan"]["items"]
        assert {x["agent"] for x in before["agents"] if x["writes"]} == {"planner", "antifomo", "replanner"}
        assert before["changes"] and before["skips"]

        b.start(keep_graph=True)  # a second API process on another port, same graph
        assert b.port != a.port
        assert b.call("GET", "/agents/state")["plan"] == before["plan"]
        assert a.call("GET", "/agents/state")["plan"] == before["plan"]

        a.restart()  # read back from FalkorDB by a fresh process
        after = a.call("GET", "/agents/state")
        assert after["plan"] == before["plan"]
        assert after["skips"] == before["skips"] and after["changes"] == before["changes"]
    finally:
        a.stop()
        b.stop()
