"""(6) Bright Data answers 429: at most 2 retries (3 requests) per call, then fallback. Never more."""

from __future__ import annotations

import asyncio
from datetime import date

import pytest
from _resilience import QUERY, FakeBrightData
from fastapi.testclient import TestClient

from conferge.api.app import create_app
from conferge.api.providers import Providers
from conferge.core.brightdata import BrightDataError
from conferge.flights.airports import airport_pairs
from conferge.flights.brightdata_provider import BrightDataFlightsProvider
from conferge.flights.service import FlightSearchQuery, FlightService
from conferge.integration.assemble import assemble
from conferge.integration.sources import fixture_slices
from conferge.integration.stays_flights import LiveDomain
from conferge.lodging.booking import BookingSource
from conferge.lodging.service import LodgingService

MAX_REQUESTS = 3  # first attempt + 2 retries
FLIGHTS = FlightSearchQuery(origin_city="New York", destination_city="San Francisco",
                            departure_date=date(2026, 10, 27), return_date=date(2026, 10, 30))


def test_client_stops_after_two_retries(bd_429: FakeBrightData) -> None:
    async def call() -> None:
        async with bd_429.client() as client:
            await client.scrape_dataset("gd_resilience", [{"url": "https://example.org"}])

    with pytest.raises(BrightDataError, match="HTTP 429"):
        asyncio.run(call())
    assert len(bd_429.hits) == MAX_REQUESTS


def test_429_providers_fall_back_after_bounded_retries(bd_429: FakeBrightData) -> None:
    async def search() -> tuple[object, object]:
        booking = BookingSource(client=bd_429.client())
        stays = (await LodgingService(sources={"booking": booking}).search(QUERY)).envelope
        booking_hits = len(bd_429.hits)
        assert booking_hits == MAX_REQUESTS, bd_429.hits
        bd_429.hits.clear()
        provider = BrightDataFlightsProvider(client=bd_429.client())
        flights = await FlightService(providers=[("brightdata", provider)]).search(
            FLIGHTS, allow_fixture=True)
        return stays, flights

    stays, flights = asyncio.run(search())
    pairs = airport_pairs(FLIGHTS.origin_city, FLIGHTS.destination_city, include_secondary=False)
    assert len(bd_429.hits) == MAX_REQUESTS * len(pairs), (len(bd_429.hits), len(pairs))
    assert stays.items == [] and stays.status == "failed"  # type: ignore[attr-defined]
    assert any("HTTP 429" in e for e in stays.errors)  # type: ignore[attr-defined]
    # Flights: the service's explicit fixture fallback, labelled fixture, never live.
    assert flights.source_mode == "fixture" and flights.status == "degraded"  # type: ignore[attr-defined]
    assert all(e.source_mode == "fixture" for o in flights.items for e in o.evidence)  # type: ignore[attr-defined]
    assert all(r.status == "failed" for r in flights.reports)  # type: ignore[attr-defined]

    stays_domain = LiveDomain("stays", [], stays.source_mode, stays.status,  # type: ignore[attr-defined]
                              stays.collected_at, [], list(stays.errors))  # type: ignore[attr-defined]
    demo = assemble(fixture_slices(), {"stays": stays_domain}).demo
    body = TestClient(create_app(data=demo, found=Providers(), graph_probe=False)) \
        .get("/api/v1/stays").json()
    assert body["data_source"] == "fixture"
    assert any("HTTP 429" in w and "fixture fallback" in w for w in body["warnings"])
