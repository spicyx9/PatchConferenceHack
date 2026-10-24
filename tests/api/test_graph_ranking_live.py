"""MET written to FalkorDB changes the ranking and survives a process restart (needs FalkorDB).

Run: CONFERGE_FALKORDB_TEST=1 FALKORDB_PORT=6380 uv run pytest tests/api/test_graph_ranking_live.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.skipif(
    os.getenv("CONFERGE_FALKORDB_TEST") != "1",
    reason="set CONFERGE_FALKORDB_TEST=1 with a running FalkorDB to run",
)
GRAPH = "conferge_w00_rank_live"
TOP_PEOPLE = (
    "from fastapi.testclient import TestClient;"
    "from conferge.api.app import create_app;"
    "from conferge.api.providers import Providers;"
    "import json;"
    "b = TestClient(create_app(found=Providers())).get('/api/v1/people?limit=5').json();"
    "print(json.dumps({'ids': [c['person']['id'] for c in b['items']], 'mode': b['data_source']}))"
)


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
    yield
    store.graph.delete()


def _restarted_top() -> dict:
    out = subprocess.run([sys.executable, "-c", TOP_PEOPLE], capture_output=True, text=True,
                         env={**os.environ, "FALKORDB_GRAPH": GRAPH}, timeout=120, check=True)
    return json.loads(out.stdout.strip().splitlines()[-1])


def test_met_drops_person_and_survives_restart(graph_env) -> None:  # type: ignore[no-untyped-def]
    from conferge.api.app import create_app
    from conferge.api.providers import Providers

    client = TestClient(create_app(found=Providers()))
    before = [c["person"]["id"] for c in client.get("/api/v1/people?limit=5").json()["items"]]
    assert before, "graph ranking returned nobody"
    met = client.post("/api/v1/met", json={"person_id": before[0]}).json()
    assert met["persisted"] == "falkordb" and met["ranking_mode"] == "graph"
    after = [c["person"]["id"] for c in client.get("/api/v1/people?limit=5").json()["items"]]
    assert before[0] not in after  # dropped: the graph memory query excludes MET
    restarted = _restarted_top()  # new Python process, nothing shared but FalkorDB
    assert restarted["mode"] != "degraded_no_graph"
    assert restarted["ids"] == after
