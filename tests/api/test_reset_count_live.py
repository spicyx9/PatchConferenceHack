"""Rehearsal bug 5: ``graph_memory_cleared`` must count the Meeting and Change nodes it deletes.

Measured on a real FalkorDB (not a fake): the driver's ``nodes_deleted`` statistic is right for
DETACH DELETE, and the API reports it as is. The rehearsal's ``nodes_deleted: 0`` was a second
reset after the first had already removed the nodes (the 36 relationships were the PLANS/SKIPS
edges rewritten by the reload in between).

Run: CONFERGE_FALKORDB_TEST=1 FALKORDB_PORT=6380 uv run pytest tests/api/test_reset_count_live.py
"""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.skipif(
    os.getenv("CONFERGE_FALKORDB_TEST") != "1",
    reason="set CONFERGE_FALKORDB_TEST=1 with a running FalkorDB to run",
)
GRAPH = "conferge_bug5_reset_count"


@pytest.fixture()
def graph_env(monkeypatch):  # type: ignore[no-untyped-def]
    from conferge.api.data import load_fixture
    from conferge.api.logic import parse_goals
    from conferge.core.store import connect_graph
    from conferge.graph import GraphBundle, ingest_bundle

    monkeypatch.setenv("FALKORDB_GRAPH", GRAPH)
    store = connect_graph()
    try:
        store.graph.delete()
    except Exception:  # noqa: BLE001 - absent graph
        pass
    store = connect_graph()
    store.ensure_indexes(force=True)
    data = load_fixture()
    ingest_bundle(store, GraphBundle(
        source_mode="fixture", conference=data.conference, companies=data.companies,
        people=data.people, events=data.events, goals=parse_goals(data.demo_goal_text)))
    yield store
    store.graph.delete()


def _count(store, label: str) -> int:  # type: ignore[no-untyped-def]
    rows = store.graph.ro_query(f"MATCH (n:{label} {{user_id: 'demo-user'}}) RETURN count(n)").result_set
    return int(rows[0][0])


def test_reset_reports_the_meeting_and_change_nodes_it_deleted(graph_env) -> None:  # type: ignore[no-untyped-def]
    from conferge.api.app import create_app
    from conferge.api.providers import Providers
    from conferge.graph.agent_state import write_change

    store = graph_env
    client = TestClient(create_app(found=Providers()))
    plan = client.get("/api/v1/plan").json()
    assert plan["ranking_mode"] == "graph" and plan["plan_graph"]  # PLANS edges written
    client.post("/api/v1/met", json={"person_id": plan["people"][0]["person_ids"][0]})
    first = plan["plan"]["days"][0]["items"][0]["event_id"]
    write_change(store, "demo-user", label="test change", scenario_id="s", event_ids=[first],
                 from_version=1, written_by="test")
    assert (_count(store, "Meeting"), _count(store, "Change")) == (1, 1)

    cleared = client.post("/api/v1/reset").json()["graph_memory_cleared"]
    assert cleared["nodes_deleted"] == 2  # one Meeting, one Change: the driver counter is right
    assert cleared["relationships_deleted"] >= 2  # MET edge, AFFECTS edge, and the PLANS edges
    assert (_count(store, "Meeting"), _count(store, "Change")) == (0, 0)

    again = client.post("/api/v1/reset").json()["graph_memory_cleared"]
    assert again["nodes_deleted"] == 0  # nothing left to delete: the rehearsal's reading
