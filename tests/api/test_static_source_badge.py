"""Static UI: travel items show their collection channel (source badge) and never compute a flight price."""

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


def test_source_api_badge_helper_is_used_on_stays_and_itinerary() -> None:
    js = _app_js()
    helper = _body(js, "sourceApiBadge")
    assert 'if (!src || typeof src !== "object") return "";' in helper  # degrades when source is absent
    assert "title=" in helper and "snapshot_id" in helper and "esc(" in helper
    assert "sourceApiBadge(st.source)" in _body(js, "renderStays")
    travel = _body(js, "renderTravel")
    assert travel.count("sourceApiBadge(leg.source)") == 2  # flight and stay legs
    assert "sourceBadge(leg.source_mode)" in travel  # existing badge kept
    assert "flightPriceText(leg)" in travel


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
    assert "linkedinField(c.linkedin)" in _body(js, "renderPeople")
    field = _body(js, "linkedinField")
    assert "li.headline" in field and "li.company" in field and "identity_confidence" in field
    assert "presence" not in field.replace("never presence", "")  # LinkedIn never claims presence
