"""Offline tests for the Bright Data Google Flights adapter.

The collect_by_url record shape follows a row trimmed from a real response
published by S1xinch/flight-finder (tests/lib.test.ts); values are fictional.
"""

from datetime import date, datetime, timezone

import httpx
import pytest

from conferge.core.brightdata import BrightDataClient
from conferge.core.schemas import SourceRecord
from conferge.flights.brightdata_provider import (
    BrightDataFlightsProvider,
    build_input,
    record_to_raw_offer,
    resolve_segment_times,
)
from conferge.flights.normalize import build_offer

NOW = datetime(2026, 10, 24, 18, 0, tzinfo=timezone.utc)
TFS = "https://www.google.com/travel/flights/booking?tfs=FAKE{n}"


def _leg(day, o, d, dep, arr, travel, number):
    return {
        "date": f"{day}T00:00:00.000Z", "origin_airport": o, "destination_airport": d,
        "segments": [{
            "airline_name": "Test Air", "marketing_code": "ZZ", "flight_number": number,
            "aircraft_name": "Test 737", "depart_time": dep, "depart_airport_iata": o,
            "arrive_time": arr, "arrive_airport_iata": d,
            "segment_travel_time_text": f"Travel time: {travel}", "layover_after": None,
        }],
    }


def _detail(n=1, legs=None):
    return {
        "url": TFS.format(n=n), "itinerary_id": f"FAKE{n}",
        "pricing": {"best_total_price": 412 + n, "currency": "USD"},
        "providers": [{"provider_name": "Test Air", "provider_type": "Airline",
                       "primary_price": 412 + n, "link": "https://www.google.com/travel/clk/f?u=x"}],
        "legs": legs if legs is not None else [
            _leg("2026-10-27", "JFK", "SFO", "8:00", "11:30", "6 hr 30 min", f"10{n}"),
            _leg("2026-10-30", "SFO", "JFK", "13:00", "21:35", "5 hr 35 min", f"20{n}"),
        ],
    }


def _record(payload):
    return SourceRecord(provider="brightdata_google_flights", source_id="x", source_mode="live",
                        collected_at=NOW, payload=payload, source_url=payload.get("url"))


def test_build_input_uses_google_labels():
    data = build_input("JFK", "SFO", date(2026, 10, 27), date(2026, 10, 30))
    assert data["trip_type"] == "Round trip" and data["cabin"] == "Economy"
    assert data["departure"] == "2026-10-27" and data["return"] == "2026-10-30"


def test_record_mapping_round_trip_with_24h_proof():
    offer = build_offer(record_to_raw_offer(_record(_detail())), NOW)
    out, back = offer.slices
    assert offer.total_price == "413" and offer.currency == "USD"
    assert offer.booking_url_type == "google_flights_booking"
    assert out.segments[0].departure_at.isoformat() == "2026-10-27T08:00:00-04:00"
    assert out.segments[0].arrival_at.isoformat() == "2026-10-27T11:30:00-07:00"
    assert back.segments[0].departure_at.isoformat() == "2026-10-30T13:00:00-07:00"
    assert out.segments[0].marketing_carrier == "ZZ"
    assert offer.evidence[0].source_mode == "live"


def test_ambiguous_bare_clock_stays_unknown():
    dep, arr, warning = resolve_segment_times(
        date(2026, 10, 27), "7", "10:15", "JFK", "SFO", 375)
    assert dep is None and arr is None and "ambiguous" in warning
    dep, arr, warning = resolve_segment_times(
        date(2026, 10, 27), "7:00 PM", "10:15 PM", "JFK", "SFO", 375)
    assert dep.hour == 19 and arr.hour == 22 and warning is None
    dep, arr, warning = resolve_segment_times(
        date(2026, 10, 27), "10:30 PM", "7:05 AM", "SFO", "JFK", 335)
    assert arr.date() == date(2026, 10, 28)


def test_partial_round_trip_record_is_not_an_offer():
    payload = _detail(legs=[_leg("2026-10-27", "JFK", "SFO", "8:00", "11:30", "6 hr 30 min",
                                 "101")])
    raw = record_to_raw_offer(_record(payload))
    assert raw.trip_type == "one_way"  # a single leg is never presented as a round trip


def _client(handler):
    transport = httpx.MockTransport(handler)
    return BrightDataClient("secret-key", client=httpx.AsyncClient(
        base_url="https://api.brightdata.com", transport=transport), retries=0)


async def test_url_only_discovery_then_collect_by_url():
    calls = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(req)
        if req.url.params.get("type") == "discover_new":
            return httpx.Response(200, json=[{"url": TFS.format(n=1), "itinerary_id": "FAKE1"},
                                             {"url": TFS.format(n=2), "itinerary_id": "FAKE2"}])
        url = __import__("json").loads(req.content)["input"][0]["url"]
        return httpx.Response(200, json=[_detail(int(url[-1]))])

    provider = BrightDataFlightsProvider(_client(handler), poll_interval=0)
    offers, report = await provider.search_round_trip(
        "JFK", "SFO", date(2026, 10, 27), date(2026, 10, 30))
    assert len(offers) == 2 and report.status == "ok" and report.termination == "exhausted"
    assert calls[0].url.params["discover_by"] == "input_filters"
    assert sum(1 for c in calls if "discover_by" not in c.url.params) == 2
    assert {o.total_price for o in offers} == {"413", "414"}


async def test_collect_failure_is_degraded_not_hidden():
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.params.get("type") == "discover_new":
            return httpx.Response(200, json=[{"url": TFS.format(n=1)}, {"url": TFS.format(n=2)}])
        url = __import__("json").loads(req.content)["input"][0]["url"]
        if url.endswith("2"):
            return httpx.Response(500, json={})
        return httpx.Response(200, json=[_detail(1)])

    provider = BrightDataFlightsProvider(_client(handler), poll_interval=0)
    offers, report = await provider.search_round_trip(
        "JFK", "SFO", date(2026, 10, 27), date(2026, 10, 30))
    assert len(offers) == 1 and report.status == "degraded"
    assert any("collect_by_url failed" in e for e in report.errors)
    assert all("secret-key" not in e for e in report.errors)


async def test_snapshot_polling_and_schema_change():
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path.endswith("/scrape"):
            return httpx.Response(202, json={"snapshot_id": "s1"})
        return httpx.Response(200, json=[{"url": TFS.format(n=1), "legs": [], "pricing": {
            "best_total_price": 1}}])

    provider = BrightDataFlightsProvider(_client(handler), poll_interval=0)
    offers, report = await provider.search_round_trip(
        "JFK", "SFO", date(2026, 10, 27), date(2026, 10, 30))
    assert offers == [] and report.status == "failed"
    assert report.termination == "schema_changed"


async def test_missing_key_fails_visibly():
    provider = BrightDataFlightsProvider(BrightDataClient(None), poll_interval=0)
    offers, report = await provider.search_round_trip(
        "JFK", "SFO", date(2026, 10, 27), date(2026, 10, 30))
    assert offers == [] and report.status == "failed"
    assert "key missing" in report.errors[0]


@pytest.mark.parametrize("rows", [[], [{"error": "blocked", "error_code": "blocked"}]])
async def test_zero_results_is_failure(rows):
    provider = BrightDataFlightsProvider(_client(lambda req: httpx.Response(200, json=rows)))
    offers, report = await provider.search_round_trip(
        "JFK", "SFO", date(2026, 10, 27), date(2026, 10, 30))
    assert offers == [] and report.status == "failed"
