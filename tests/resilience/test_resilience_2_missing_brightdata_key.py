"""(2) No Bright Data key: missing_credentials, fallback (Airbnb/fast-flights or fixture), no price invented."""

from __future__ import annotations

import asyncio
from datetime import date
from decimal import Decimal

from _resilience import QUERY, live_only
from fastapi.testclient import TestClient

from conferge.api.app import create_app
from conferge.api.providers import Providers
from conferge.flights.brightdata_provider import BrightDataFlightsProvider
from conferge.flights.service import FlightSearchQuery, FlightService
from conferge.integration.assemble import assemble
from conferge.integration.sources import fixture_slices
from conferge.integration.stays_flights import LiveDomain, collect_stays_flights
from conferge.lodging.booking import BookingSource
from conferge.lodging.google_hotels import GoogleHotelsSource
from conferge.lodging.service import LodgingService

FLIGHTS = FlightSearchQuery(origin_city="New York", destination_city="San Francisco",
                            departure_date=date(2026, 10, 27), return_date=date(2026, 10, 30))


def _domain(name: str, env: object) -> LiveDomain:
    return LiveDomain(name, list(env.items), env.source_mode, env.status,  # type: ignore[attr-defined]
                      env.collected_at, [], list(env.errors))  # type: ignore[attr-defined]


def _assert_no_invented_price(items: list[dict]) -> None:
    for item in items:
        price = item.get("total_price")
        if price is None:
            continue
        assert Decimal(str(price)) > 0, item["id"]
        assert item["price_status"] not in {"unknown", "unavailable"}, item["id"]


async def _bd_only() -> tuple[object, object, list]:
    reports = [(await BookingSource().search(QUERY)).run_report,
               (await GoogleHotelsSource().search(QUERY)).run_report]
    stays = (await LodgingService(sources={"booking": BookingSource(),
                                           "google_hotels": GoogleHotelsSource()})
             .search(QUERY)).envelope
    flights = await FlightService(providers=[("brightdata", BrightDataFlightsProvider())]).search(
        FLIGHTS)
    return stays, flights, reports


def test_missing_key_reports_missing_credentials_and_falls_back_to_fixture(
    no_brightdata_key: None,
) -> None:
    stays, flights, reports = asyncio.run(_bd_only())
    for rep in reports:
        assert rep.status == "failed" and rep.fetched_count == 0
        assert any("missing_credentials" in e for e in rep.errors), rep.errors
    assert stays.items == [] and stays.status == "failed"  # type: ignore[attr-defined]
    assert flights.items == [] and flights.status == "failed"  # type: ignore[attr-defined]
    assert any("key missing" in e.lower() for e in flights.errors)  # type: ignore[attr-defined]

    demo = assemble(fixture_slices(), {"stays": _domain("stays", stays),
                                       "flights": _domain("flights", flights)}).demo
    client = TestClient(create_app(data=demo, found=Providers(), graph_probe=False))
    for path in ("/api/v1/stays", "/api/v1/flights"):
        body = client.get(path).json()
        assert body["data_source"] == "fixture" and body["status"] == "degraded"
        assert any("fixture fallback" in w for w in body["warnings"])
        assert body["items"]
        _assert_no_invented_price(body["items"])


@live_only
def test_missing_key_falls_back_to_airbnb_and_fast_flights(no_brightdata_key: None) -> None:
    live = asyncio.run(collect_stays_flights(90.0))
    demo = assemble(fixture_slices(), live).demo
    client = TestClient(create_app(data=demo, found=Providers(), graph_probe=False))
    stays = client.get("/api/v1/stays").json()
    flights = client.get("/api/v1/flights").json()
    for body in (stays, flights):
        assert body["data_source"] in {"live", "fixture"}
        if body["data_source"] == "live":
            assert body["status"] == "degraded"  # Bright Data providers failed, visibly
            assert all(e["source_mode"] == "live" for i in body["items"] for e in i["evidence"])
        _assert_no_invented_price(body["items"])
    assert {i["provider"] for i in stays["items"]} <= {"airbnb"} or stays["data_source"] == "fixture"
