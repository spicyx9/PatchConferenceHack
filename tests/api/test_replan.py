"""Dynamic sold-out scenario: bound to the top plan event, readable replan diff."""

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


def test_sold_out_targets_top_plan_event_and_explains_replacement() -> None:
    client = _client()
    plan = client.get("/api/v1/plan").json()["plan"]
    items = [i for d in plan["days"] for i in d["items"]]
    top = max(items, key=lambda i: i["score"])

    body = client.post("/api/v1/simulate-change", json={"scenario_id": "top-sold-out"}).json()

    assert body["changed_events"] == [top["event_id"]]
    assert [r["event_id"] for r in body["diff"]["removed"]] == [top["event_id"]]
    entry = body["replan"][0]
    assert entry["removed"]["event_id"] == top["event_id"]
    assert entry["removed"]["status"] == "sold_out"
    assert top["title"] in entry["reason"] and "simulated" in entry["reason"]
    replacement = entry["replacement"]
    assert replacement is not None
    assert replacement["event_id"] in {a["event_id"] for a in body["diff"]["added"]}
    assert replacement["title"] in entry["reason"]
    if replacement["people"]:
        path = entry["graph_path"]
        assert path["nodes"][0] == "You" and path["person_id"] == replacement["people"][0]["person_id"]


def test_dynamic_target_follows_the_plan_after_reset() -> None:
    client = _client()
    first = client.post("/api/v1/simulate-change", json={"scenario_id": "top-sold-out"}).json()
    client.post("/api/v1/reset")
    again = client.post("/api/v1/simulate-change", json={"scenario_id": "top-sold-out"}).json()
    assert first["changed_events"] == again["changed_events"]
    assert again["diff"]["removed"]


def test_knock_on_removals_are_explained_as_displaced() -> None:
    from conferge.api import logic
    from conferge.api.data import load_fixture

    data = load_fixture()
    event = data.events[0]
    before = {"days": [{"day": "d", "items": [
        {"event_id": event.id, "title": "Changed", "start_at": None, "score": 9, "people": []},
        {"event_id": "other", "title": "Bumped", "start_at": None, "score": 1, "people": []},
    ]}]}
    after = {"days": [{"day": "d", "items": []}]}
    replan = logic.explain_replan(before, after, [event.id], data)
    assert [r["removed"]["event_id"] for r in replan] == [event.id, "other"]
    assert "simulated change" in replan[0]["reason"]
    assert "simulated" not in replan[1]["reason"] and replan[1]["replacement"] is None


def test_search_falls_back_to_api_dataset_without_falkordb() -> None:
    body = _client().get("/api/v1/search", params={"q": "founders"}).json()
    assert body["backend"] == "api-fallback"
    assert body["events"] or body["people"]
