from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx

from conferge.travel.places import EMBARCADERO, FORT_MASON, SFO
from conferge.travel.providers.base import RouteProvider
from conferge.travel.providers.osrm import DRIVE_WARNING, OsrmProvider

OK_BODY = {
    "code": "Ok",
    "routes": [{"legs": [{}], "duration": 1722.9, "distance": 26300}],
    "waypoints": [{}, {}],
}


def provider_for(handler, seen: list[httpx.Request] | None = None) -> OsrmProvider:
    def wrapped(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        return handler(request)

    return OsrmProvider(client=httpx.AsyncClient(transport=httpx.MockTransport(wrapped)))


def test_protocol() -> None:
    assert isinstance(OsrmProvider(), RouteProvider)


async def test_drive_parse() -> None:
    seen: list[httpx.Request] = []
    out = await provider_for(lambda r: httpx.Response(200, json=OK_BODY), seen).route(
        SFO, FORT_MASON, mode="drive"
    )
    assert seen[0].url.host == "router.project-osrm.org"
    assert "/route/v1/driving/-122.379,37.6213;-122.432,37.806" in str(seen[0].url)
    assert seen[0].url.params["overview"] == "false"
    (leg,) = out.legs
    assert leg.duration_minutes == 29
    assert leg.duration_status == "estimate"
    assert leg.distance_m == 26300
    assert leg.price.status == "unknown" and leg.price.amount is None
    assert leg.provider == "osrm" and leg.source_mode == "live"
    assert leg.collected_at.tzinfo is not None
    assert str(leg.source_url) == str(seen[0].url)
    assert leg.warnings == [DRIVE_WARNING]
    assert leg.evidence[0].provider == "osrm"
    assert leg.departure_local is None and leg.arrival_local is None
    rep = out.run_report
    assert (rep.status, rep.termination, rep.fetched_count, rep.pages) == (
        "ok", "exhausted", 1, 1,
    )


async def test_walk_url_and_price() -> None:
    seen: list[httpx.Request] = []
    out = await provider_for(lambda r: httpx.Response(200, json=OK_BODY), seen).route(
        EMBARCADERO, FORT_MASON, mode="walk"
    )
    assert seen[0].url.host == "routing.openstreetmap.de"
    assert seen[0].url.path.startswith("/routed-foot/route/v1/foot/")
    (leg,) = out.legs
    assert leg.mode == "walk"
    assert leg.price.amount == "0" and leg.price.status == "exact"
    assert leg.price.currency == "USD"
    assert leg.warnings == ["OSRM foot profile estimate"]


async def test_arrival_from_depart_at() -> None:
    depart = datetime(2026, 10, 27, 23, 0, tzinfo=timezone.utc)
    out = await provider_for(lambda r: httpx.Response(200, json=OK_BODY)).route(
        SFO, FORT_MASON, mode="drive", depart_at=depart
    )
    (leg,) = out.legs
    assert leg.departure_local == depart
    assert leg.departure_local.utcoffset() == timedelta(hours=-7)
    assert leg.arrival_local == depart + timedelta(seconds=1722.9)


async def test_naive_depart_at_fails() -> None:
    out = await provider_for(lambda r: httpx.Response(200, json=OK_BODY)).route(
        SFO, FORT_MASON, mode="drive", depart_at=datetime(2026, 10, 27, 16, 0)
    )
    assert out.legs == [] and out.run_report.status == "failed"


async def test_no_route_failed() -> None:
    body = {"code": "NoRoute", "message": "Impossible route between points"}
    out = await provider_for(lambda r: httpx.Response(400, json=body)).route(
        SFO, FORT_MASON, mode="drive"
    )
    assert out.legs == []
    assert out.run_report.status == "failed"
    assert out.run_report.termination == "error"
    assert "NoRoute" in out.run_report.errors[0]


async def test_empty_routes_failed() -> None:
    out = await provider_for(
        lambda r: httpx.Response(200, json={"code": "Ok", "routes": []})
    ).route(SFO, FORT_MASON, mode="drive")
    assert out.legs == [] and out.run_report.status == "failed"


async def test_rate_limited() -> None:
    out = await provider_for(lambda r: httpx.Response(429, text="Too Many Requests")).route(
        SFO, FORT_MASON, mode="drive"
    )
    assert out.legs == []
    assert out.run_report.status == "failed"
    assert out.run_report.termination == "rate_limited"


async def test_schema_changed() -> None:
    body = {"code": "Ok", "routes": [{"time": 1722.9, "length": 26300}]}
    out = await provider_for(lambda r: httpx.Response(200, json=body)).route(
        SFO, FORT_MASON, mode="drive"
    )
    assert out.legs == []
    assert out.run_report.status == "failed"
    assert out.run_report.termination == "schema_changed"


async def test_network_error() -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down", request=request)

    out = await provider_for(boom).route(SFO, FORT_MASON, mode="walk")
    assert out.legs == []
    assert (out.run_report.status, out.run_report.termination) == ("failed", "error")


async def test_unsupported_mode() -> None:
    out = await OsrmProvider().route(SFO, FORT_MASON, mode="bart")
    assert out.legs == [] and out.run_report.status == "failed"
