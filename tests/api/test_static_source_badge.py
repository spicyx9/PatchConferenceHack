"""Travel cards show price freshness and booking sites; collection channels stay internal."""

from __future__ import annotations

import re

from fastapi.testclient import TestClient

from conferge.api.app import create_app
from conferge.api.providers import Providers


def _app_js() -> str:
    client = TestClient(create_app(found=Providers(), graph_probe=False))
    res = client.get("/static/app.js")
    assert res.status_code == 200
    return res.text


def _body(js: str, name: str) -> str:
    start = js.index(f"function {name}(")
    nxt = js.find("\n  function ", start + 1)
    return js[start:nxt if nxt != -1 else len(js)]


def test_travel_cards_do_not_expose_collection_tools() -> None:
    js = _app_js()
    for name in ("renderStays", "renderFlights"):
        body = _body(js, name)
        assert "travelPriceBadge(" in body
        assert "sourceApiBadge(" not in body and "sourceBadge(" not in body
    assert "sourceApiBadge(" not in _body(js, "searchTravel")



def test_flight_price_falls_back_to_raw_text_without_computing() -> None:
    body = _body(_app_js(), "flightPriceText")
    assert "f.raw_price_text" in body and "observed price" in body
    assert not re.search(r"[*/]|parseFloat|Number\(", body.replace("// ", ""))


def test_home_counter_reports_brightdata_share_of_stays_and_flights() -> None:
    js = _app_js()
    assert 'it.source.provider === "brightdata"' in _body(js, "bdShare")
    assert "Flights via Bright Data" in _body(js, "renderBrightData")


def test_data_pipeline_panel_with_reachability_reads_the_api() -> None:
    js = _app_js()
    client = TestClient(create_app(found=Providers(), graph_probe=False))
    html = client.get("/").text
    for element_id in ("pipeline-panel", "pipeline-headline", "pipeline-table", "pipeline-calls", "pipeline-reach"):
        assert f'id="{element_id}"' in html
    assert 'api("/pipeline", null, null)' in js
    assert "renderReachability(res && res.reachability)" in _body(js, "renderPipeline")
    reach = _body(js, "renderReachability")
    assert "reachable_without_brightdata" in reach and "kyc_pending" in reach


def test_people_cards_show_linkedin_headline_and_company() -> None:
    js = _app_js()
    assert "linkedinField(card.linkedin)" in _body(js, "renderPeople")
    field = _body(js, "linkedinField")
    assert "li.headline" in field and "li.company" in field and "identity_confidence" in field
    assert "presence" not in field.replace("never presence", "")  # LinkedIn never claims presence
