"""Risk 2 of the wiring audit: a simulated change must stay visible on every later response."""

from __future__ import annotations

from fastapi.testclient import TestClient

from conferge.api.app import create_app
from conferge.api.data import load_fixture
from conferge.api.providers import Providers


def _client() -> TestClient:
    data = load_fixture()
    data.scenarios.append({
        "id": "top-sold-out", "label": "SIMULATION: top plan event sold out",
        "changes": [{"target": "top_plan_event", "set": {"status": "sold_out"}}],
    })
    return TestClient(create_app(data=data, found=Providers(), graph_probe=False))


def _simulation_warnings(body: dict) -> list[str]:
    return [w for w in body["warnings"] if w.startswith("simulated change active")]


def test_events_plan_and_map_warn_while_a_simulation_is_active() -> None:
    client = _client()
    for path in ("/api/v1/events", "/api/v1/plan", "/api/v1/travel/map"):
        assert not _simulation_warnings(client.get(path).json()), path

    sim = client.post("/api/v1/simulate-change", json={"scenario_id": "top-sold-out"}).json()
    changed = set(sim["changed_events"])
    assert changed

    for path in ("/api/v1/events", "/api/v1/plan", "/api/v1/travel/map"):
        assert _simulation_warnings(client.get(path).json()), path

    items = client.get("/api/v1/events").json()["items"]
    flagged = {i["id"] for i in items if i["simulated"]}
    assert flagged == changed
    assert all(i["status"] == "sold_out" for i in items if i["id"] in changed)

    client.post("/api/v1/reset")
    after = client.get("/api/v1/events").json()
    assert not _simulation_warnings(after)
    assert not any(i["simulated"] for i in after["items"])
