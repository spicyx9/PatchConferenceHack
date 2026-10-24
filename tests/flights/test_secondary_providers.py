"""Offline tests for the SerpApi and fast-flights secondary providers (test-only data)."""

from __future__ import annotations

import sys
from datetime import date, timedelta

import httpx

from conferge.flights.fastflights_provider import FastFlightsProvider
from conferge.flights.serpapi_provider import SerpApiFlightsProvider

KEY = "test-secret-key-000"
OUT_DATE, RET_DATE = date(2026, 10, 27), date(2026, 10, 30)
SEARCH_URL = "https://www.google.com/travel/flights?test=fixture"


def _flight(dep: str, arr: str, dep_time: str, arr_time: str, number: str, minutes: int):
    return {
        "departure_airport": {"name": f"{dep} test", "id": dep, "time": dep_time},
        "arrival_airport": {"name": f"{arr} test", "id": arr, "time": arr_time},
        "duration": minutes, "airplane": "Test Jet", "airline": "Test Air",
        "flight_number": number,
    }


OUTBOUND = {
    "search_metadata": {"id": "test-search-out", "google_flights_url": SEARCH_URL},
    "best_flights": [{
        "flights": [_flight("JFK", "SFO", "2026-10-27 08:00", "2026-10-27 11:30", "UA 1234", 390)],
        "total_duration": 390, "price": 410, "type": "Round trip", "departure_token": "TOK_A",
    }],
    "other_flights": [{
        "flights": [_flight("JFK", "SFO", "2026-10-27 15:00", "2026-10-27 18:20", "B6 915", 380)],
        "total_duration": 380, "price": 450, "type": "Round trip", "departure_token": "TOK_B",
    }],
}


def _return(token: str, price: int, number: str) -> dict:
    return {
        "search_metadata": {"id": f"test-search-ret-{token}", "google_flights_url": SEARCH_URL},
        "best_flights": [{
            "flights": [_flight("SFO", "JFK", "2026-10-30 09:00", "2026-10-30 17:35", number, 335)],
            "total_duration": 335, "price": price, "booking_token": f"SECRETBOOK_{token}",
        }, {
            "flights": [_flight("SFO", "JFK", "2026-10-30 22:00", "2026-10-31 06:30", number, 330)],
            "total_duration": 330, "price": price + 100, "booking_token": f"SECRETBOOK2_{token}",
        }],
    }


RETURNS = {"TOK_A": _return("TOK_A", 520, "UA 1235"), "TOK_B": _return("TOK_B", 560, "B6 916")}


def _transport(calls: list[httpx.Request]):
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        token = request.url.params.get("departure_token")
        return httpx.Response(200, json=RETURNS[token] if token else OUTBOUND)
    return httpx.MockTransport(handler)


async def test_missing_key_fails_without_request(monkeypatch):
    monkeypatch.delenv("SERPAPI_KEY", raising=False)
    calls: list[httpx.Request] = []
    async with httpx.AsyncClient(transport=_transport(calls)) as client:
        offers, report = await SerpApiFlightsProvider(client=client).search_round_trip(
            "JFK", "SFO", OUT_DATE, RET_DATE)
    assert offers == [] and calls == []
    assert report.status == "failed" and report.errors == ["SERPAPI_KEY missing"]


async def test_round_trip_happy_path():
    calls: list[httpx.Request] = []
    async with httpx.AsyncClient(transport=_transport(calls)) as client:
        offers, report = await SerpApiFlightsProvider(KEY, client).search_round_trip(
            "JFK", "SFO", OUT_DATE, RET_DATE)
    assert len(calls) == 3
    first = calls[0].url.params
    assert first["type"] == "1" and first["travel_class"] == "1" and first["no_cache"] == "true"
    assert report.status == "ok" and report.termination == "exhausted"
    assert len(offers) == 2
    by_price = {o.total_price: o for o in offers}
    assert set(by_price) == {"520", "560"}
    offer = by_price["520"]
    assert offer.currency == "USD" and offer.trip_type == "round_trip"
    assert len(offer.slices) == 2
    assert str(offer.booking_url) == SEARCH_URL
    assert offer.booking_url_type == "google_flights_search"
    dumped = offer.model_dump_json()
    assert "SECRETBOOK" not in dumped and KEY not in dumped
    out_seg, ret_seg = offer.slices[0].segments[0], offer.slices[1].segments[0]
    assert out_seg.flight_number == "UA1234" and out_seg.marketing_carrier == "UA"
    assert out_seg.departure_at.utcoffset() == timedelta(hours=-4)  # America/New_York EDT
    assert out_seg.arrival_at.utcoffset() == timedelta(hours=-7)  # America/Los_Angeles PDT
    assert ret_seg.departure_at.utcoffset() == timedelta(hours=-7)
    assert ret_seg.arrival_at.utcoffset() == timedelta(hours=-4)
    ev = offer.evidence[0]
    assert ev.source_mode == "live" and ev.raw_ref == "test-search-ret-TOK_A"
    assert ev.collected_at is not None and ev.collected_at.tzinfo is not None


async def test_max_returns_caps_and_degrades():
    calls: list[httpx.Request] = []
    async with httpx.AsyncClient(transport=_transport(calls)) as client:
        offers, report = await SerpApiFlightsProvider(KEY, client, max_returns=1).search_round_trip(
            "JFK", "SFO", OUT_DATE, RET_DATE)
    assert len(offers) == 1 and offers[0].total_price == "520"
    assert report.status == "degraded" and report.termination == "page_cap"
    assert any(w.startswith("partial_roundtrip") for w in report.warnings)


async def test_http_401_fails_without_leaking_key():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "Invalid API key."})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        offers, report = await SerpApiFlightsProvider(KEY, client).search_round_trip(
            "JFK", "SFO", OUT_DATE, RET_DATE)
    assert offers == [] and report.status == "failed"
    assert "401" in report.errors[0]
    assert KEY not in report.model_dump_json()


async def test_fast_flights_not_installed(monkeypatch):
    monkeypatch.setitem(sys.modules, "fast_flights", None)
    offers, report = await FastFlightsProvider().search_round_trip(
        "JFK", "SFO", OUT_DATE, RET_DATE)
    assert offers == [] and report.status == "failed"
    assert "fast-flights not installed" in report.errors[0]
