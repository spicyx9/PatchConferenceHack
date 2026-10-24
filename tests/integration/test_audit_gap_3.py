"""Audit BRIGHTDATA_E2E_2026-10-24: gap 3 (one truth for the flight) and secondary gaps.

1. The Web Unlocker round-trip total is stored as shown: FalkorDB, /api/v1/flights and
   /api/v1/travel carry the same trip_type / total_price / price_status (FalkorDB part needs
   FALKORDB_HOST/FALKORDB_PORT, graph ``conferge_w4``; skipped when it does not answer).
2. The Bright Data Airbnb stays are shown next to the Booking ones.
3. ``scripts/run_probe.py <slug>`` hands the probe only its own options.
4. fast-flights counts a SERP call only when the zone really served the page.
"""

from __future__ import annotations

import asyncio
import subprocess
import sys
import types
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace as NS
from typing import Any

import pytest
from fastapi.testclient import TestClient

from conferge.api.app import create_app
from conferge.api.data import load_fixture
from conferge.api.provenance import source_of
from conferge.api.providers import Providers
from conferge.integration import travel_cache

ROOT = Path(__file__).resolve().parents[2]
FIELDS = ("trip_type", "total_price", "currency", "price_status", "return_slice_collected",
          "raw_price_text")


def _cached_data() -> Any:
    cache = travel_cache.load()
    assert cache and "flights" in cache and "stays" in cache
    data = load_fixture()
    data.flights, data.stays = cache["flights"].items, cache["stays"].items
    return data


# -- 1. one truth for the flight -----------------------------------------------------------

def test_cached_web_unlocker_flight_is_stored_as_shown() -> None:
    flight = _cached_data().flights[0]
    assert (flight.trip_type, flight.price_status, flight.return_slice_collected) == (
        "round_trip", "quoted_total", False)
    assert flight.raw_price_text == f"{flight.total_price} {flight.currency} round trip total"
    assert len(flight.slices) == 1  # the return slice is not on the page


def test_api_flights_and_travel_read_the_stored_fields() -> None:
    data = _cached_data()
    stored = data.flights[0]
    client = TestClient(create_app(data=data, found=Providers(), graph_probe=False))
    item = next(i for i in client.get("/api/v1/flights").json()["items"] if i["id"] == stored.id)
    assert {k: item[k] for k in FIELDS} == {k: getattr(stored, k) for k in FIELDS}
    assert item["price_label"] == "round trip total"
    travel = client.get("/api/v1/travel").json()
    leg = next(x for x in travel["itinerary"] if x["kind"] == "flight")
    assert (leg["total_price"], leg["currency"], leg["price_status"],
            leg["return_slice_collected"]) == (stored.total_price, stored.currency,
                                               stored.price_status, False)
    assert travel["budget"]["flights_usd"] == stored.total_price
    assert travel["budget"]["flights_price_status"] == [stored.price_status]


def test_falkordb_holds_what_the_api_shows(monkeypatch: pytest.MonkeyPatch) -> None:
    from conferge.core.store import connect_graph, connect_graph_or_none
    from conferge.graph import GraphBundle, ingest_bundle

    monkeypatch.setenv("FALKORDB_GRAPH", "conferge_w4")
    if connect_graph_or_none(timeout=0.5) is None:
        pytest.skip("FalkorDB not reachable (FALKORDB_HOST/FALKORDB_PORT)")
    store = connect_graph()
    try:
        store.graph.delete()
    except Exception:  # noqa: BLE001 - absent graph
        pass
    store = connect_graph()
    try:
        data = _cached_data()
        ingest_bundle(store, GraphBundle(source_mode="live", conference=data.conference,
                                         flights=data.flights))
        stored = data.flights[0]
        (node,) = store.graph.query(
            "MATCH (f:FlightOffer {id: $id}) RETURN properties(f)", params={"id": stored.id}
        ).result_set[0]
        client = TestClient(create_app(data=data, found=Providers(), graph_probe=False))
        item = next(i for i in client.get("/api/v1/flights").json()["items"]
                    if i["id"] == stored.id)
        leg = next(x for x in client.get("/api/v1/travel").json()["itinerary"]
                   if x["kind"] == "flight")
        print("graph:", {k: node.get(k) for k in FIELDS})
        print("api  :", {k: item[k] for k in FIELDS})
        assert {k: node.get(k) for k in FIELDS} == {k: item[k] for k in FIELDS}
        assert (node["total_price"], node["price_status"]) == (leg["total_price"],
                                                               leg["price_status"])
        assert node["trip_type"] == "round_trip" and node["return_slice_collected"] is False
    finally:
        store.graph.delete()


# -- 2. Airbnb stays are shown ------------------------------------------------------------

def test_bright_data_airbnb_stays_are_shown_with_their_provenance() -> None:
    data = _cached_data()
    sites = Counter(source_of(s.evidence)["site"] for s in data.stays)
    assert sites == {"booking": 6, "airbnb": 6}
    assert source_of(data.stays[0].evidence)["site"] == "booking"  # the budget stay is unchanged
    client = TestClient(create_app(data=data, found=Providers(), graph_probe=False))
    items = client.get("/api/v1/stays").json()["items"]
    airbnb = [i for i in items if i["source"]["site"] == "airbnb"]
    assert len(airbnb) == 6
    assert all(i["source"]["provider"] == "brightdata" and i["source"]["api"] == "dataset"
               for i in airbnb)


# -- 3. make probe-<slug> -----------------------------------------------------------------

def test_run_probe_hands_only_the_probe_options() -> None:
    out = subprocess.run([sys.executable, "scripts/run_probe.py", "linkedin", "--help"],
                         cwd=ROOT, capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    assert "usage: linkedin.py" in out.stdout and "unrecognized arguments" not in out.stderr


def test_makefile_probe_target_passes_args() -> None:
    out = subprocess.run(["make", "-n", "probe-linkedin", "ARGS=--no-collect"], cwd=ROOT,
                         capture_output=True, text=True, timeout=30)
    assert 'scripts/run_probe.py "linkedin" --no-collect' in out.stdout


# -- 4. fast-flights SERP counter ---------------------------------------------------------

NOW = datetime(2026, 10, 24, 18, 0, tzinfo=timezone.utc)


def _fake_fast_flights(monkeypatch: pytest.MonkeyPatch, status: int) -> list[str]:
    calls: list[str] = []
    module = types.ModuleType("fast_flights")
    integrations = types.ModuleType("fast_flights.integrations")

    class Query:
        def __init__(self, legs: list[dict[str, Any]]) -> None:
            self.legs = legs

        def url(self) -> str:
            return "https://www.google.com/travel/flights/search?tfs=FAKE"

    class BrightData:
        def __init__(self, *, api_key: str, zone: str) -> None:
            self.zone = zone
            self.client = NS(post=lambda *a, **k: NS(status_code=status, text="<html/>"))

        def fetch_html(self, q: Query) -> str:
            return self.client.post("https://api.brightdata.com/request",
                                    json={"url": q.url(), "zone": self.zone}).text

    def get_flights(query: Query, integration: Any = None) -> list[Any]:
        calls.append("zone" if integration else "direct")
        if integration:
            integration.fetch_html(query)  # the body is returned whatever the status
        leg = query.legs[0]
        day = (2026, 10, 27) if leg["from_airport"] == "JFK" else (2026, 10, 30)
        return [NS(type="ZZ", price=372, flights=[NS(
            from_airport=NS(code=leg["from_airport"]), to_airport=NS(code=leg["to_airport"]),
            departure=NS(date=day, time=(7, 0)), arrival=NS(date=day, time=(10, 0)),
            duration=360, plane_type=None)])]

    module.FlightQuery = lambda **kw: kw
    module.Passengers = lambda **kw: kw
    module.create_query = lambda **kw: Query(kw["flights"])
    module.get_flights = get_flights
    integrations.BrightData = BrightData
    module.integrations = integrations
    monkeypatch.setitem(sys.modules, "fast_flights", module)
    monkeypatch.setitem(sys.modules, "fast_flights.integrations", integrations)
    monkeypatch.setenv("BRIGHTDATA_API_KEY", "k")
    monkeypatch.setenv("BRIGHTDATA_SERP_ZONE", "serp_api1")
    return calls


def _search() -> tuple[list[Any], Any]:
    from conferge.flights.fastflights_provider import FastFlightsProvider

    return asyncio.run(FastFlightsProvider(clock=lambda: NOW).search_round_trip(
        "JFK", "SFO", date(2026, 10, 27), date(2026, 10, 30)))


def test_serp_is_counted_only_when_the_zone_answered(monkeypatch: pytest.MonkeyPatch) -> None:
    from conferge.core import brightdata

    calls = _fake_fast_flights(monkeypatch, status=200)
    brightdata.reset_usage()
    offers, _ = _search()
    assert calls == ["zone", "zone"] and brightdata.usage()["returned"]["serp"] == 2
    src = source_of(offers[0].evidence)
    assert (src["provider"], src["api"], src["id"]) == ("brightdata", "serp", "serp_api1")


def test_a_failed_zone_call_is_not_counted_and_not_badged(monkeypatch: pytest.MonkeyPatch) -> None:
    from conferge.core import brightdata

    calls = _fake_fast_flights(monkeypatch, status=401)
    brightdata.reset_usage()
    offers, report = _search()
    assert brightdata.usage()["returned"]["serp"] == 0
    assert Counter(calls) == {"zone": 2, "direct": 2}  # each page refetched directly
    assert source_of(offers[0].evidence)["provider"] == "fast-flights"
    assert any("bright_data_serp_not_used" in w and "401" in w for w in report.warnings)
