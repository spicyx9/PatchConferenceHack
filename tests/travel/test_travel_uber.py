from __future__ import annotations

import json

import httpx

from conferge.core.brightdata import BrightDataClient
from conferge.travel.places import FORT_MASON, SFO
from conferge.travel.providers.base import RouteProvider
from conferge.travel.providers.uber import (
    ESTIMATOR_URL,
    NO_FARE_WARNING,
    UberEstimateProvider,
    parse_uberx_range,
)

KEY = "fake-key"


def bd_client(handler, seen: list[httpx.Request] | None = None) -> BrightDataClient:
    def wrapped(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        return handler(request)

    http = httpx.AsyncClient(
        base_url="https://api.brightdata.com", transport=httpx.MockTransport(wrapped)
    )
    return BrightDataClient(KEY, unlocker_zone="z", client=http, retries=0)


def test_protocol() -> None:
    assert isinstance(UberEstimateProvider(BrightDataClient(None)), RouteProvider)


async def test_no_key_failed() -> None:
    out = await UberEstimateProvider(BrightDataClient(None, unlocker_zone="z")).route(
        SFO, FORT_MASON, mode="rideshare"
    )
    assert out.legs == []
    assert out.run_report.status == "failed"
    assert out.run_report.termination == "error"
    assert "BRIGHTDATA_API_KEY" in out.run_report.errors[0]


async def test_no_zone_failed() -> None:
    out = await UberEstimateProvider(BrightDataClient(KEY)).route(
        SFO, FORT_MASON, mode="rideshare"
    )
    assert out.legs == [] and out.run_report.status == "failed"
    assert all(KEY not in e for e in out.run_report.errors)


async def test_http_403_blocked() -> None:
    out = await UberEstimateProvider(bd_client(lambda r: httpx.Response(403))).route(
        SFO, FORT_MASON, mode="rideshare"
    )
    assert out.legs == []
    assert out.run_report.termination == "blocked"
    assert all(KEY not in e for e in out.run_report.errors)


async def test_uberx_fare_parsed() -> None:
    html = "<div><h3>UberX</h3><p>Affordable rides</p><span>$45-$60</span></div>"
    seen: list[httpx.Request] = []
    out = await UberEstimateProvider(
        bd_client(lambda r: httpx.Response(200, text=html), seen)
    ).route(SFO, FORT_MASON, mode="rideshare")
    body = json.loads(seen[0].content)
    assert body["zone"] == "z" and body["url"].startswith(ESTIMATOR_URL)
    (leg,) = out.legs
    assert leg.mode == "rideshare"
    assert leg.price.amount == "45"
    assert leg.price.status == "estimate"
    assert leg.price.currency == "USD"
    assert leg.price.fare_class == "uberx_range_low"
    assert "45-60" in leg.price.note
    assert leg.duration_minutes is None and leg.duration_status == "unknown"
    assert leg.provider == "uber_estimator" and leg.source_mode == "live"
    assert str(leg.source_url).startswith(ESTIMATOR_URL)
    assert (out.run_report.status, out.run_report.termination) == ("ok", "exhausted")


async def test_no_fare_degraded() -> None:
    html = "<html><body><div id='root'></div><script>window.__APP__={}</script></body></html>"
    out = await UberEstimateProvider(bd_client(lambda r: httpx.Response(200, text=html))).route(
        SFO, FORT_MASON, mode="rideshare"
    )
    assert out.legs == []
    assert out.run_report.status == "degraded"
    assert out.run_report.termination == "schema_changed"
    assert out.run_report.warnings == [NO_FARE_WARNING]


def test_fare_far_from_uberx_ignored() -> None:
    html = "UberX" + " " * 300 + "$45-$60"
    assert parse_uberx_range(html) is None
    assert parse_uberx_range("Comfort $45 - $60") is None
    assert parse_uberx_range("UberX $38.50 – $52.00") == ("38.50", "52.00")


async def test_unsupported_mode() -> None:
    out = await UberEstimateProvider(BrightDataClient(None)).route(
        SFO, FORT_MASON, mode="walk"
    )
    assert out.legs == [] and out.run_report.status == "failed"
