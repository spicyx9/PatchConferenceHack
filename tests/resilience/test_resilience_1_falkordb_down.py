"""(1) FalkorDB down (closed port): the API answers, degraded_no_graph, accessible status, no 500."""

from __future__ import annotations

import re

import pytest
from _resilience import closed_port
from fastapi.testclient import TestClient

from conferge.api.app import create_app

GETS = ("/health", "/api/v1/sources", "/api/v1/conference", "/api/v1/plan", "/api/v1/search?q=ai",
        "/api/v1/antifomo", "/api/v1/people", "/api/v1/events", "/api/v1/sessions",
        "/api/v1/stays", "/api/v1/flights", "/api/v1/travel", "/api/v1/travel/map",
        "/api/v1/graph", "/api/v1/scenarios", "/api/v1/roi")


def test_falkordb_closed_port_degrades_visibly_without_500(monkeypatch: pytest.MonkeyPatch) -> None:
    port = closed_port()
    monkeypatch.setenv("FALKORDB_HOST", "127.0.0.1")
    monkeypatch.setenv("FALKORDB_PORT", str(port))
    client = TestClient(create_app(), raise_server_exceptions=False)  # real defaults, probe on

    codes = {path: client.get(path).status_code for path in GETS}
    assert all(code < 500 for code in codes.values()), codes
    assert client.get("/health").json()["graph_up"] is False

    people = client.get("/api/v1/people").json()
    assert people["data_source"] == "degraded_no_graph" and people["status"] == "degraded"
    assert any("degraded_no_graph" in w for w in people["warnings"])
    assert client.get("/api/v1/plan").json()["data_source"] == "degraded_no_graph"

    pid = people["items"][0]["person"]["id"]
    posts = [
        client.post("/api/v1/goal", json={"text": "meet seed investors"}),
        client.get("/api/v1/graph/path", params={"person": pid}),
        client.post("/api/v1/met", json={"person_id": pid}),
        client.post("/api/v1/reset"),
    ]
    assert all(r.status_code < 500 for r in posts), [(r.url, r.status_code) for r in posts]
    assert client.post("/api/v1/met", json={"person_id": pid}).json()["data_source"] != "live"

    # Front: fallback status is explicit, accessible, and driven by the API mode.
    html = client.get("/").text
    assert 'id="degraded-banner"' in html and "degraded_no_graph" in html
    js = client.get("/static/app.js").text
    assert re.search(r'data_source === "degraded_no_graph"', js)
    assert re.search(r'"degraded-banner"\)\.classList\.toggle\("hidden", !degraded\)', js)
    assert re.search(r'id="degraded-banner"[^>]*role="status"', html, re.S)
    assert "Graph unavailable" in html
