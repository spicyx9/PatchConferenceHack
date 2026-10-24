"""/api/v1/calendar.ics exports the optimized plan (My agenda), not every discovered event."""

from __future__ import annotations

import hashlib
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from conferge.api.app import create_app
from conferge.api.providers import Providers
from conferge.extras.router import router


def _uid(event_id: str) -> str:
    return hashlib.sha256(event_id.encode("utf-8")).hexdigest()[:24] + "@conferge"


def _plan_ids(client: TestClient) -> list[str]:
    plan = client.get("/api/v1/plan").json()["plan"]
    return [i["event_id"] for d in plan["days"] for i in d["items"]]


def test_calendar_download_is_valid_ics_with_only_selected_events() -> None:
    app = FastAPI()
    event = {"id": "github-universe-26", "title": "GitHub Universe", "status": "scheduled",
             "start_at": "2026-10-28T10:00:00-07:00", "end_at": "2026-10-28T12:00:00-07:00"}
    other = {**event, "id": "not-planned", "title": "Not planned"}
    app.state.demo = SimpleNamespace(
        data=SimpleNamespace(events=[event, other]),
        plan=lambda: {"days": [{"day": "2026-10-28", "items": [{"event_id": "github-universe-26"}]}]},
    )
    app.include_router(router)
    with TestClient(app) as client:
        response = client.get("/api/v1/calendar.ics")
    assert response.status_code == 200
    assert "text/calendar" in response.headers["content-type"]
    assert 'filename="conferge-plan.ics"' in response.headers["content-disposition"]
    assert response.text.count("BEGIN:VEVENT") == 1
    assert "DTSTART:20261028T170000Z" in response.text and "Not planned" not in response.text


def test_calendar_follows_the_agenda_after_skips_and_replanning() -> None:
    client = TestClient(create_app(found=Providers(), graph_probe=False))
    planned = _plan_ids(client)
    ics = client.get("/api/v1/calendar.ics").text
    events = client.get("/api/v1/events").json()["count"]
    assert 0 < ics.count("BEGIN:VEVENT") <= len(planned) < events  # the plan, not all discovered events
    assert all(_uid(e) in ics for e in planned)

    skipped = planned[0]
    assert client.post("/api/v1/skipped", json={"event_id": skipped, "reason": "not_interested"}).status_code == 200
    assert skipped not in _plan_ids(client)
    ics = client.get("/api/v1/calendar.ics").text
    assert _uid(skipped) not in ics

    scenarios = client.get("/api/v1/scenarios").json()["items"]
    if scenarios:
        before = set(_plan_ids(client))
        sim = client.post("/api/v1/simulate-change", json={"scenario_id": scenarios[0]["id"]}).json()
        after = set(_plan_ids(client))
        ics = client.get("/api/v1/calendar.ics").text
        for removed in before - after:
            assert _uid(removed) not in ics
        for added in after - before:
            assert _uid(added) in ics
        assert sim["changed_events"]


def test_agenda_has_the_export_button() -> None:
    from pathlib import Path

    html = (Path(__file__).resolve().parents[2] / "static" / "index.html").read_text()
    agenda = html[html.index('id="tab-events"'):html.index("Explore events")]
    assert 'href="/api/v1/calendar.ics"' in agenda
