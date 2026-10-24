"""(3) A scraper times out (0.1 s): clean fallback, RunReport status != exhausted, status shown."""

from __future__ import annotations

import asyncio
import re
from datetime import date

import pytest
from _resilience import QUERY, FakeBrightData, live_only
from fastapi.testclient import TestClient

from conferge.api.app import create_app
from conferge.api.providers import Providers
from conferge.flights.brightdata_provider import BrightDataFlightsProvider
from conferge.flights.fastflights_provider import FastFlightsProvider
from conferge.flights.service import FlightSearchQuery, FlightService
from conferge.integration.assemble import assemble
from conferge.integration.sources import fixture_slices
from conferge.integration.stays_flights import LiveDomain
from conferge.lodging.booking import BookingSource
from conferge.lodging.service import LodgingService

TIMEOUT = 0.1
FLIGHTS = FlightSearchQuery(origin_city="New York", destination_city="San Francisco",
                            departure_date=date(2026, 10, 27), return_date=date(2026, 10, 30))


def _domain(name: str, env: object) -> LiveDomain:
    return LiveDomain(name, list(env.items), env.source_mode, env.status,  # type: ignore[attr-defined]
                      env.collected_at, [], list(env.errors))  # type: ignore[attr-defined]


async def _search(server: FakeBrightData) -> tuple[object, object]:
    booking = BookingSource(client=server.client(timeout=TIMEOUT))
    stays = (await LodgingService(sources={"booking": booking}).search(QUERY)).envelope
    provider = BrightDataFlightsProvider(client=server.client(timeout=TIMEOUT))
    flights = await FlightService(providers=[("brightdata", provider)]).search(FLIGHTS)
    return stays, flights


def test_timeout_falls_back_cleanly_and_the_status_is_shown(bd_slow: FakeBrightData) -> None:
    stays, flights = asyncio.run(_search(bd_slow))
    reports = [*stays.reports, *flights.reports]  # type: ignore[attr-defined]
    assert reports
    for rep in reports:
        assert rep.status == "failed", rep
        assert rep.termination != "exhausted", rep
        assert rep.fetched_count == 0
    errors = [*stays.errors, *flights.errors]  # type: ignore[attr-defined]
    assert any(re.search(r"network error|timeout", e, re.I) for e in errors), errors

    demo = assemble(fixture_slices(), {"stays": _domain("stays", stays),
                                       "flights": _domain("flights", flights)}).demo
    client = TestClient(create_app(data=demo, found=Providers(), graph_probe=False))
    for path in ("/api/v1/stays", "/api/v1/flights"):
        body = client.get(path).json()
        assert body["data_source"] == "fixture" and body["status"] == "degraded"
        assert any("fixture fallback" in w and re.search(r"network error|timeout", w, re.I)
                   for w in body["warnings"]), body["warnings"]
    js = client.get("/static/app.js").text
    assert 'var st = $("badge-status")' in js  # the global status badge reads envelope.status
    assert "statusBadge" in js


@live_only
def test_fast_flights_timeout_is_a_failed_report(monkeypatch: pytest.MonkeyPatch) -> None:
    service = FlightService(providers=[("fastflights", FastFlightsProvider())])
    monkeypatch.setattr(service, "provider_timeout", TIMEOUT)
    env = asyncio.run(service.search(FLIGHTS))
    assert env.items == [] and env.status == "failed"
    for rep in env.reports:
        assert rep.status == "failed" and rep.termination != "exhausted"
        assert any("timeout" in e for e in rep.errors), rep.errors
