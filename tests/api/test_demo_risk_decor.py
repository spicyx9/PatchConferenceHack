"""Risk 5 of the wiring audit: the demo decor must never pass for live data.

The traveller profile (city, dates, budget) always comes from ``fixtures/api.json``, even when
events are collected live; a travel proposal books nothing; map routes are straight lines.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from conferge.api.app import create_app
from conferge.api.data import load_fixture
from conferge.api.providers import Providers
from conferge.integration.assemble import assemble
from conferge.integration.sources import fixture_slices


def _client() -> TestClient:
    return TestClient(create_app(data=load_fixture(), found=Providers(), graph_probe=False))


def test_traveller_profile_is_labelled_fixture_in_assembly_and_fixture_load() -> None:
    assert load_fixture().user["source_mode"] == "fixture"
    assert assemble(fixture_slices()).demo.user["source_mode"] == "fixture"


def test_budget_carries_the_profile_source_mode() -> None:
    body = _client().get("/api/v1/travel").json()
    assert body["budget"]["source_mode"] == "fixture"
    assert body["budget"]["budget_usd"] == load_fixture().user["budget_usd"].__str__()


def test_proposals_declare_they_book_nothing() -> None:
    client = _client()
    proposals = client.get("/api/v1/travel").json()["proposals"]
    assert proposals and all(p["books"] is False for p in proposals)
    res = client.post("/api/v1/proposal/accept", json={"proposal_id": proposals[0]["id"]}).json()
    noted = next(p for p in res["proposals"] if p["id"] == proposals[0]["id"])
    assert noted["accepted"] is True and noted["books"] is False
    assert noted["status_label"] == "Noted as preferred"


def test_noting_a_proposal_changes_no_flight_or_stay() -> None:
    client = _client()
    before = client.get("/api/v1/travel").json()
    pid = before["proposals"][0]["id"]
    assert before["proposals"][0]["status_label"] is None
    after = client.post("/api/v1/proposal/accept", json={"proposal_id": pid}).json()
    assert after["itinerary"] == before["itinerary"] and after["budget"] == before["budget"]
    assert next(p for p in after["proposals"] if p["id"] == pid)["status_label"] == "Noted as preferred"


def test_map_routes_are_declared_straight_lines() -> None:
    body = _client().get("/api/v1/travel/map").json()
    assert body["polylines"]
    assert {p["kind"] for p in body["polylines"]} == {"straight_line_order_of_visits"}


def test_ui_shows_the_decor_labels() -> None:
    js = open("static/app.js", encoding="utf-8").read()
    html = open("static/index.html", encoding="utf-8").read()
    assert "Straight lines, not routes" in js
    assert "sourceModeBadge(b.source_mode)" in js
    assert ">Noted</button>" in js and ">Noted as preferred</span>" in js and ">Accept</button>" not in js
    assert 'id="map-kind"' in html
