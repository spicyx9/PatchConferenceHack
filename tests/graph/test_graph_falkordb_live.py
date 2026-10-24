"""Opt-in FalkorDB integration: CONFERGE_FALKORDB_TEST=1 FALKORDB_PORT=... uv run pytest.

Uses a scratch graph that is deleted afterwards; never touches FALKORDB_GRAPH.
"""

from __future__ import annotations

import os

import pytest

from conferge.core.store import GraphStore
from conferge.graph import queries as Q
from conferge.graph.bundle import ingest_bundle
from conferge.graph.memory import record_memory
from conferge.graph.seed import load_graph_fixture

pytestmark = pytest.mark.skipif(
    os.getenv("CONFERGE_FALKORDB_TEST") != "1",
    reason="set CONFERGE_FALKORDB_TEST=1 with a running FalkorDB to run",
)


@pytest.fixture()
def store():
    from falkordb import FalkorDB

    db = FalkorDB(host=os.getenv("FALKORDB_HOST", "127.0.0.1"),
                  port=int(os.getenv("FALKORDB_PORT", "6379")),
                  password=os.getenv("FALKORDB_PASSWORD") or None)
    graph = db.select_graph("conferge_w08_pytest")
    try:
        graph.delete()
    except Exception:  # noqa: BLE001 - absent graph
        pass
    yield GraphStore(graph)
    graph.delete()


def test_seed_is_idempotent_and_demo_paths_exist(store):
    ingest_bundle(store, load_graph_fixture())
    first = Q.graph_counts(store)
    ingest_bundle(store, load_graph_fixture())
    assert Q.graph_counts(store) == first
    assert "ATTENDS_CONFIRMED" in first["edges"] and first["edges"]["ATTENDS_CONFIRMED"] == 1

    people = Q.people_for_goal(store, "demo-user", "g-agent-founders")
    multi_hop = [r for r in people["rows"] if 2 <= r["shortest_hops"] <= 4]
    assert len(multi_hop) >= 5
    assert "p-fx-gina" not in {r["person_id"] for r in people["rows"]}
    assert all(p["edges"] for p in people["paths"])


def test_memory_changes_ranking_and_queries_return_paths(store):
    ingest_bundle(store, load_graph_fixture())
    before = Q.people_for_goal(store, "demo-user", "g-agent-founders")["rows"]
    top = before[0]["person_id"]
    record_memory(store, "demo-user", "MET", "Person", top)
    after = [r["person_id"] for r in Q.people_for_goal(store, "demo-user",
                                                       "g-agent-founders")["rows"]]
    assert top not in after
    assert Q.people_met_before(store, "demo-user")["rows"][0]["person_id"] == top

    overlaps = [c for c in Q.conflicts(store, "github-universe-2026")["rows"]
                if c["kind"] == "overlap"]
    assert overlaps and overlaps[0]["distance_m"] is not None
    assert Q.path_user_to_person(store, "demo-user", top)["paths"]
    replan = Q.replan_after_change(store, "e-fx-agents-night", {"status": "sold_out"})
    assert replan["rows"][0]["impacted_people"] == ["p-fx-carol"]
    ui = Q.graph_for_ui(store, "github-universe-2026")
    assert ui["rows"][0]["node_count"] > 20 and ui["paths"][0]["edges"]
