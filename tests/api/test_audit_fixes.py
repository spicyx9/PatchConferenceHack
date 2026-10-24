"""Audit fixes (figures shown in the UI must come from the graph, a RunReport or user input)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from conferge.api import app as app_module
from conferge.api import logic, providers
from conferge.api.data import load_fixture
from conferge.core.store import GraphStore


class _MeetingGraph:
    """Answers only the MET Meeting read; any other query fails like a graph without data."""

    def __init__(self, rows: list[list[Any]]) -> None:
        self.rows = rows
        self.queries: list[str] = []

    def query(self, q: str, params: dict[str, Any] | None = None) -> Any:
        self.queries.append(q)
        if "Meeting" in q and "RETURN p.id, m.note, m.at" in q:
            return SimpleNamespace(result_set=self.rows)
        raise RuntimeError("not in this fake graph")


def test_fix3_meetings_are_restored_from_the_graph_at_startup(monkeypatch: pytest.MonkeyPatch) -> None:
    data = load_fixture()
    pid = data.people[0].id
    graph = _MeetingGraph([[pid, "talked about seed", "2026-10-28T18:05:00+00:00"],
                           ["person:not-in-dataset", None, None]])
    monkeypatch.setattr(providers, "connect_store", lambda: GraphStore(graph))
    state = app_module.DemoState(data, providers.Providers(), graph_probe=True)
    assert state.met == {pid: "talked about seed"}
    assert state.met_at[pid].isoformat() == "2026-10-28T18:05:00+00:00"
    assert logic.roi_view(state.data, state.goals, [], state.met)["meetings"] == 1
    assert not any("MERGE" in q or "CREATE" in q for q in graph.queries)  # read only


def test_fix3_without_graph_memory_starts_empty() -> None:
    state = app_module.DemoState(load_fixture(), providers.Providers(), graph_probe=False)
    assert state.met == {} and state.restore_memory() == 0


def test_fix4_spend_names_its_stay_and_carries_price_status() -> None:
    data = load_fixture()
    travel = logic.travel_view(data, {"days": []}, set())
    budget = travel["budget"]
    stay_leg = next(leg for leg in travel["itinerary"] if leg["kind"] == "stay")
    assert budget["lodging_stay"]["id"] == stay_leg["stay_id"]  # same stay as the itinerary shows
    assert budget["lodging_price_status"] == data.stays[0].price_status
    assert len(budget["flights_price_status"]) >= 1
    assert "not chosen by you" in budget["spend_basis"]
    roi = logic.roi_view(data, [], [], {})
    assert roi["spend_price_status"]["lodging"] == budget["lodging_price_status"]
    assert roi["spend_basis"] == budget["spend_basis"]
    if budget["lodging_usd"] is None:  # fixture prices are not collected: nothing is estimated
        assert roi["spend_usd"] is None


def _js_function(name: str) -> str:
    from pathlib import Path

    js = (Path(__file__).resolve().parents[2] / "static" / "app.js").read_text()
    start = js.index(f"function {name}(")
    nxt = js.find("\n  function ", start + 1)
    return js[start:nxt if nxt != -1 else len(js)]


def test_fix5_every_amount_in_the_ui_shows_its_price_status() -> None:
    assert "leg.price_status" in _js_function("renderFlights")
    assert "st.price_status" in _js_function("renderStays")
    # Research does not subtract unselected offers from a remaining budget.
    assert "b.remaining_usd" not in _js_function("renderTravel")
    assert "spend_price_status" in _js_function("renderRoi")



def test_fix6_budget_is_labelled_as_a_demo_assumption() -> None:
    data = load_fixture()
    budget = logic.travel_view(data, {"days": []}, set())["budget"]
    assert budget["budget_usd"] == str(data.user["budget_usd"])
    assert "demo persona assumption" in budget["budget_source"]
    assert logic.roi_view(data, [], [], {})["budget_source"] == budget["budget_source"]
    assert "b.budget_source" in _js_function("renderTravel")
    assert "roi.budget_source" in _js_function("renderRoi")


def test_fix9_conference_name_and_dates_come_from_the_data() -> None:
    from pathlib import Path

    html = (Path(__file__).resolve().parents[2] / "static" / "index.html").read_text()
    assert "GitHub Universe 2026" not in html and "October 28" not in html  # no hard-coded fact
    render = _js_function("renderConference")
    assert "conf.name" in render and "conf.start_date" in render and "conf.end_date" in render


def test_fix1_draft_never_asserts_where_the_meeting_happened() -> None:
    from fastapi.testclient import TestClient

    from conferge.api.app import create_app

    client = TestClient(create_app(found=providers.Providers(), graph_probe=False))
    data = load_fixture()
    person = next(p for p in data.people if any(data.event(e) for e in p.event_ids))
    event = next(data.event(e) for e in person.event_ids if data.event(e))
    client.post("/api/v1/met", json={"person_id": person.id, "note": "seed round"})
    draft = client.get("/api/v1/followup", params={"person": person.id}).json()
    assert f"at {data.conference.name}" in draft["message"] and event.title not in draft["message"]
    assert draft["based_on"]["event"] is None and draft["based_on"]["person_event"] == event.title
    client.post("/api/v1/attended", json={"event_id": event.id})  # the user says they were there
    draft = client.get("/api/v1/followup", params={"person": person.id}).json()
    assert f"Good to meet you at {event.title}" in draft["message"]


def test_fix2_drafts_show_their_facts_and_warnings() -> None:
    facts = _js_function("followupFacts")
    for key in ("based_on", "warnings", "person_event", "note", "path"):
        assert key in facts
    from pathlib import Path

    js = (Path(__file__).resolve().parents[2] / "static" / "app.js").read_text()
    assert "followupFacts(draft)" in js


def test_fix7_artwork_is_labelled_as_a_dated_capture() -> None:
    from conferge.api.artwork import event_artwork, fixture_captured_at, load_fixture_covers

    covers = load_fixture_covers()
    data = load_fixture()
    with_cover = [e for e in data.events if e.id in covers]
    captured = fixture_captured_at()
    for event in with_cover:
        art = event_artwork(event, covers)
        if art:
            assert art["cover_source_mode"] == "fixture" and art["cover_captured_at"] == captured
    art_js = _js_function("eventArtwork")
    assert "cover_captured_at" in art_js and "Luma capture" in art_js


def test_fix8_threshold_is_a_returned_parameter_and_people_total_is_not_capped() -> None:
    from fastapi.testclient import TestClient

    from conferge.api.app import create_app

    roi = logic.roi_view(load_fixture(), [], [], {})
    assert roi["opportunity_threshold"] == logic.OPPORTUNITY_THRESHOLD
    client = TestClient(create_app(found=providers.Providers(), graph_probe=False))
    page = client.get("/api/v1/people", params={"limit": 3}).json()
    assert page["count"] <= 3 and page["total"] >= page["count"]
    assert "p.total" in _js_function("renderPeople")
    assert "roi.opportunity_threshold" in _js_function("renderRoi")


def test_fix10_generated_cover_is_labelled_in_the_ui() -> None:
    from pathlib import Path

    html = (Path(__file__).resolve().parents[2] / "static" / "index.html").read_text()
    assert "Illustration generated with AI, not a photo of the event" in html
