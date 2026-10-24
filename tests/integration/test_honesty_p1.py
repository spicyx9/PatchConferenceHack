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


# -- 2. "Meet: X" only with SPEAKS_AT / HOSTS ---------------------------------------------

def test_meet_only_for_confirmed_speakers_or_hosts() -> None:
    from conferge.api import logic

    data = load_fixture()
    client = _client()
    client.post("/api/v1/goal", json={"text": data.demo_goal_text, "user_id": "demo-user"})
    plan = client.get("/api/v1/plan").json()["plan"]
    people = [(i["event_id"], p) for d in plan["days"] for i in d["items"] for p in i["people"]]
    people += [(c["loser"]["event_id"], p) for c in plan["conflicts"] for p in c["what_you_miss"]]
    assert people and all("confirmed" in p for _, p in people)
    for event_id, p in people:
        event = data.event(event_id)
        edge = p["person_id"] in event.speaker_ids + event.organizer_ids or (
            event_id in data.person(p["person_id"]).event_ids
            and data.person(p["person_id"]).participation in {"confirmed_speaker",
                                                              "confirmed_organizer"})
        assert p["confirmed"] is edge
    # an attendee listing gives a possible, never confirmed, meeting
    attendee = next((q for q in data.people if q.event_ids and q.participation not in
                     {"confirmed_speaker", "confirmed_organizer"}), None)
    if attendee:
        ev = next(e for e in data.events if e.id in attendee.event_ids)
        if attendee.id not in ev.speaker_ids + ev.organizer_ids:
            assert logic.confirmed_at(data, ev, attendee.id) is False
    assert 'Possibly: " + names(maybe) + " (not confirmed)"' in APP_JS
    assert "var who = meetLine(i.people);" in APP_JS and "meetLine(r.people)" in APP_JS


# -- 3. stay cards: guests and nights next to the price -----------------------------------

def test_stay_card_says_adults_and_nights_next_to_the_price() -> None:
    import subprocess

    js = (ROOT / "static" / "travel-cards.js").read_text(encoding="utf-8")
    script = js + """
    ;var html = window.TravelCards.stay({name: "Chelsea Inn", check_in: "2026-10-27",
      check_out: "2026-10-30", adults: 2, rooms: 1, total_price: "500.00", currency: "USD",
      price_status: "quoted_total", venue: {}}, "");
    console.log(html);"""
    out = subprocess.run(["node", "-e", "var window = {}; var document = {};" + script],
                         capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    assert "2 adults · 3 nights" in out.stdout
