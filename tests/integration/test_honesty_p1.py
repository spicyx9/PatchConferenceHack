"""Honesty fixes (P1): labels say what the data proves, nothing more."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from conferge.api.app import create_app
from conferge.api.data import load_fixture
from conferge.api.providers import Providers

ROOT = Path(__file__).resolve().parents[2]
APP_JS = (ROOT / "static" / "app.js").read_text(encoding="utf-8")


def _client() -> TestClient:
    return TestClient(create_app(data=load_fixture(), found=Providers(), graph_probe=False))


# -- 1. simulated sold out ----------------------------------------------------------------

def test_simulated_sold_out_is_flagged_and_labelled_as_simulated() -> None:
    client = _client()
    client.post("/api/v1/goal", json={"text": load_fixture().demo_goal_text, "user_id": "demo-user"})
    scenario = client.get("/api/v1/scenarios").json()["items"][0]["id"]
    res = client.post("/api/v1/simulate-change", json={"scenario_id": scenario}).json()
    changed = set(res["changed_events"])
    events = client.get("/api/v1/events").json()["items"]
    hit = [e for e in events if e["id"] in changed]
    assert hit and all(e["simulated"] and e["status"] == "sold_out" for e in hit)
    # The UI reads that flag: every sold-out label goes through statusLabel(status, id).
    assert '"Sold out (simulated scenario)"' in APP_JS
    assert "markSimulated(res.changed_events)" in APP_JS and "e.simulated" in APP_JS
    assert "eventStatus(event.status)" not in APP_JS  # the agenda card uses statusLabel
