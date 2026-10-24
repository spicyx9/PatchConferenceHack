"""Connections tab: evidence UI restored after the PR #19 redesign (graph conferge_w3)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
JS = (ROOT / "static" / "connections.js").read_text(encoding="utf-8")
HTML = (ROOT / "static" / "index.html").read_text(encoding="utf-8")


# -- 1. why: edge rationales, source_mode, evidence ids, score breakdown ------------------

def test_details_call_graph_why_and_keep_the_display_on_failure() -> None:
    assert "api(`graph/why/${encodeURIComponent(id)}`)" in JS
    assert "details(p,path);showWhy(id,ticket);" in JS
    assert '<div id="connection-why"></div>' in JS
    assert "/* keep the current display */" in JS  # a failed /graph/why changes nothing
    assert "Score breakdown:" in JS and "e.source_mode" in JS and "[ev:" in JS


def test_graph_why_returns_edges_and_score_breakdown(monkeypatch: pytest.MonkeyPatch) -> None:
    from conferge.api.app import create_app
    from conferge.api.logic import parse_goals
    from conferge.api.providers import Providers
    from conferge.core.store import connect_graph, connect_graph_or_none
    from conferge.graph import GraphBundle, ingest_bundle

    monkeypatch.setenv("FALKORDB_GRAPH", "conferge_w3")
    if connect_graph_or_none(timeout=0.5) is None:
        pytest.skip("FalkorDB not reachable (FALKORDB_HOST/FALKORDB_PORT)")
    store = connect_graph()
    try:
        store.graph.delete()
    except Exception:  # noqa: BLE001 - absent graph
        pass
    store = connect_graph()
    try:
        import asyncio

        from conferge.graph.agent_state import ensure_user
        from conferge.integration import pipeline
        from conferge.integration.assemble import assemble

        assembly = assemble(pipeline._usable(asyncio.run(pipeline._collect("fixture", False, 90.0,
                                                                            None))), None)
        data = assembly.demo
        ensure_user(store, "demo-user")
        ingest_bundle(store, GraphBundle(source_mode="fixture", conference=assembly.conference,
                                         companies=assembly.companies, people=assembly.people,
                                         events=assembly.events,
                                         goals=parse_goals(data.demo_goal_text)))
        client = TestClient(create_app(data=data, found=Providers()))
        client.post("/api/v1/goal", json={"text": data.demo_goal_text, "user_id": "demo-user"})
        cards = client.get("/api/v1/people?limit=20").json()["items"]
        whys = [client.get(f"/api/v1/graph/why/{c['person']['id']}").json() for c in cards]
        why = next((w for w in whys if w["edges"]), None)  # someone with a goal path
        assert why is not None, "no person with a goal path in the fixture graph"
        for edge in why["edges"]:
            assert {"type", "rationale", "source_mode", "evidence"} <= set(edge)
        assert why["score_breakdown"] is not None
    finally:
        store.graph.delete()
