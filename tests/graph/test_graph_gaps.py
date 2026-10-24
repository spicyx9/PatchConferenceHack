"""Absence queries on a real FalkorDB (graph conferge_w3): a goal topic absent from the graph is a gap."""

from __future__ import annotations

import socket

import pytest

from conferge.core.schemas import Goal
from conferge.core.settings import falkordb_address
from conferge.core.store import GraphStore
from conferge.graph.ingest import GraphIngestor
from conferge.graph.queries import graph_gaps
from conferge.graph.scoring_doc import how_it_works

USER = "gaps-test-user"
TOPIC = "Quantum knitting for llamas"


def _falkordb() -> GraphStore:
    host, port = falkordb_address()
    try:
        socket.create_connection((host, port), timeout=1).close()
    except OSError:
        pytest.skip(f"FalkorDB not reachable at {host}:{port}")
    from falkordb import FalkorDB

    store = GraphStore(FalkorDB(host=host, port=port).select_graph("conferge_w3"))
    try:
        store.graph.query("RETURN 1")
    except Exception:  # noqa: BLE001 - a plain Redis on that port is not FalkorDB
        pytest.skip(f"no FalkorDB at {host}:{port} (run with FALKORDB_PORT pointing to FalkorDB)")
    return store


def test_goal_with_a_topic_absent_from_the_graph_appears_in_gaps() -> None:
    store = _falkordb()
    goal = Goal(id="goal-gaps-test", description="Meet people about quantum knitting", topics=[TOPIC],
                target_roles=[], priority=1.0)
    GraphIngestor(store, default_mode="live").ingest_goals(USER, [goal])
    try:
        gaps = graph_gaps(store, USER)
        assert any(r["goal_id"] == goal.id and r["topic"] == TOPIC for r in gaps["topics_uncovered"]["rows"])
        assert any(r["goal_id"] == goal.id for r in gaps["goals_without_path"]["rows"])
        for name in ("goals_without_path", "target_companies_not_present", "topics_uncovered"):
            assert f"'{USER}'" in gaps[name]["cypher"] and gaps[name]["count"] == len(gaps[name]["rows"])
    finally:  # test cleanup of the nodes this test created (not an application write)
        store.graph.query("MATCH (g:Goal {user_id: $u}) DETACH DELETE g", params={"u": USER})
        store.graph.query("MATCH (t:Topic {name: $n}) WHERE NOT (t)--() DELETE t", params={"n": TOPIC})


def test_how_it_works_reads_the_real_constants() -> None:
    from conferge.graph import queries

    doc = how_it_works()
    assert doc["path_weights"] == queries.PATH_WEIGHTS and doc["calibrated"] is False
    assert "uncalibrated" in doc["text"] and f"speaker {queries.PATH_WEIGHTS['speaker']}" in doc["text"]
    assert "noisy-OR" in doc["text"] and "min(100" in doc["text"]
