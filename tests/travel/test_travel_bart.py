"""Offline tests for the BART schedule provider (httpx.MockTransport, no network)."""

from __future__ import annotations

import copy
from datetime import datetime, timezone
from typing import Any

import httpx

from conferge.travel.places import EMBARCADERO, FORT_MASON, SFO
from conferge.travel.providers.base import RouteProvider
from conferge.travel.providers.bart import BartProvider

KEY = "TEST-SECRET-KEY-1234"
DEPART = datetime(2026, 10, 28, 1, 0, tzinfo=timezone.utc)  # 6:00pm PDT Oct 27


def _trip(orig_time: str, dest_time: str, trip_time: str, legs: Any = None) -> dict[str, Any]:
    return {
        "@origin": "SFIA", "@destination": "EMBR", "@fare": "11.80",
        "@origTimeMin": orig_time, "@origTimeDate": "10/27/2026",
        "@destTimeMin": dest_time, "@destTimeDate": "10/27/2026",
        "@clipper": "4.40", "@tripTime": trip_time,
        "fares": {"@level": "normal", "fare": [
            {"@amount": "11.80", "@class": "clipper", "@name": "Clipper"},
            {"@amount": "5.90", "@class": "start", "@name": "Clipper START"},
            {"@amount": "4.40", "@class": "rtcclipper", "@name": "Senior/Disabled Clipper"},
            {"@amount": "5.90", "@class": "student", "@name": "Youth Clipper"},
        ]},
        "leg": legs if legs is not None else [{
            "@order": "1", "@origin": "SFIA", "@destination": "EMBR",
            "@origTimeMin": orig_time, "@origTimeDate": "10/27/2026",
            "@destTimeMin": dest_time, "@destTimeDate": "10/27/2026",
            "@line": "ROUTE 2", "@trainHeadStation": "San Francisco / Pittsburg/Bay Point",
        }],
    }


def _payload(trips: Any) -> dict[str, Any]:
    return {"root": {
        "origin": "SFIA", "destination": "EMBR",
        "schedule": {"date": "Oct 27, 2026", "time": "6:00 PM", "request": {"trip": trips}},
        "message": "",
    }}


TWO_TRIPS = _payload([
    _trip("06:00 PM", "06:31 PM", "31"),
    _trip("06:10 PM", "06:41 PM", "31"),
])


def _provider(handler, **kw) -> tuple[BartProvider, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def wrapped(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(wrapped))
    return BartProvider(KEY, client=client, **kw), seen


def _json(body: Any, status: int = 200):
    return lambda request: httpx.Response(status, json=body)


def _no_key_anywhere(outcome) -> None:
    dumped = outcome.model_dump_json()
    assert KEY not in dumped


async def test_protocol_conformance():
    prov, _ = _provider(_json(TWO_TRIPS))
    assert isinstance(prov, RouteProvider)
    assert prov.name == "bart" and prov.modes == frozenset({"bart"})


async def test_parses_two_trips():
    prov, _ = _provider(_json(TWO_TRIPS))
    out = await prov.route(SFO, EMBARCADERO, mode="bart", depart_at=DEPART)
    rr = out.run_report
    assert rr.status == "ok" and rr.termination == "exhausted"
    assert rr.fetched_count == 2 and rr.unique_count == 2 and rr.pages == 1
    assert len(out.legs) == 2
    leg = out.legs[0]
    assert str(leg.departure_local.tzinfo) == "America/Los_Angeles"
    assert (leg.departure_local.hour, leg.departure_local.minute) == (18, 0)
    assert (leg.arrival_local.hour, leg.arrival_local.minute) == (18, 31)
    assert leg.departure_local.utcoffset().total_seconds() == -7 * 3600
    assert leg.duration_minutes == 31 and leg.duration_status == "scheduled"
    assert leg.price.amount == "11.80" and leg.price.currency == "USD"
    assert leg.price.status == "exact" and leg.price.fare_class == "adult_clipper"
    assert leg.mode == "bart" and leg.provider == "bart" and leg.source_mode == "live"
    assert leg.line == "ROUTE 2" and leg.warnings == []
    assert leg.evidence and leg.evidence[0].provider == "bart"
    assert "key=" not in str(leg.source_url)
    _no_key_anywhere(out)


async def test_max_trips_limits_kept():
    prov, _ = _provider(_json(TWO_TRIPS), max_trips=1)
    out = await prov.route(SFO, EMBARCADERO, mode="bart", depart_at=DEPART)
    assert len(out.legs) == 1
    assert out.run_report.fetched_count == 2 and out.run_report.unique_count == 1


async def test_single_dict_trip_shape():
    trip = _trip("06:00 PM", "06:31 PM", "31")
    trip["leg"] = trip["leg"][0]
    trip["fares"]["fare"] = trip["fares"]["fare"][0]
    prov, _ = _provider(_json(_payload(trip)))
    out = await prov.route(SFO, EMBARCADERO, mode="bart", depart_at=DEPART)
    assert out.run_report.status == "ok"
    assert len(out.legs) == 1 and out.legs[0].price.amount == "11.80"
    assert out.legs[0].line == "ROUTE 2"


async def test_no_clipper_fare_price_unknown():
    trip = _trip("06:00 PM", "06:31 PM", "31")
    trip["fares"]["fare"] = [f for f in trip["fares"]["fare"] if f["@class"] != "clipper"]
    prov, _ = _provider(_json(_payload([trip])))
    out = await prov.route(SFO, EMBARCADERO, mode="bart", depart_at=DEPART)
    assert out.legs[0].price.status == "unknown" and out.legs[0].price.amount is None


async def test_missing_station_fails():
    prov, seen = _provider(_json(TWO_TRIPS))
    out = await prov.route(FORT_MASON, EMBARCADERO, mode="bart", depart_at=DEPART)
    assert out.legs == [] and out.run_report.status == "failed"
    assert out.run_report.termination == "error"
    assert out.run_report.errors == ["no BART station for venue-fort-mason"]
    assert seen == []


async def test_wrong_mode_fails():
    prov, seen = _provider(_json(TWO_TRIPS))
    out = await prov.route(SFO, EMBARCADERO, mode="walk", depart_at=DEPART)
    assert out.run_report.status == "failed" and seen == []


async def test_http_500_fails_without_key_leak():
    prov, seen = _provider(_json({"error": f"bad key {KEY}"}, status=500))
    out = await prov.route(SFO, EMBARCADERO, mode="bart", depart_at=DEPART)
    assert out.run_report.status == "failed" and out.run_report.termination == "error"
    assert seen and seen[0].url.params["key"] == KEY
    for err in out.run_report.errors:
        assert KEY not in err
    _no_key_anywhere(out)


async def test_http_429_rate_limited():
    prov, _ = _provider(_json({}, status=429))
    out = await prov.route(SFO, EMBARCADERO, mode="bart", depart_at=DEPART)
    assert out.run_report.status == "failed" and out.run_report.termination == "rate_limited"


async def test_network_error_fails():
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"cannot reach {request.url}", request=request)

    prov, _ = _provider(boom)
    out = await prov.route(SFO, EMBARCADERO, mode="bart", depart_at=DEPART)
    assert out.run_report.status == "failed" and out.run_report.termination == "error"
    _no_key_anywhere(out)


async def test_schema_change():
    body = {"root": {"message": {"error": {"text": f"Invalid key {KEY}"}}}}
    prov, _ = _provider(_json(body))
    out = await prov.route(SFO, EMBARCADERO, mode="bart", depart_at=DEPART)
    assert out.run_report.status == "failed"
    assert out.run_report.termination == "schema_changed"
    _no_key_anywhere(out)


async def test_zero_trips_fails():
    body = copy.deepcopy(TWO_TRIPS)
    body["root"]["schedule"]["request"]["trip"] = []
    prov, _ = _provider(_json(body))
    out = await prov.route(SFO, EMBARCADERO, mode="bart", depart_at=DEPART)
    assert out.run_report.status == "failed" and out.run_report.termination == "error"
    assert out.run_report.errors == ["zero trips"]


async def test_request_params_local_time():
    prov, seen = _provider(_json(TWO_TRIPS))
    await prov.route(SFO, EMBARCADERO, mode="bart", depart_at=DEPART)
    params = seen[0].url.params
    assert params["date"] == "10/27/2026" and params["time"] == "6:00pm"
    assert params["orig"] == "SFIA" and params["dest"] == "EMBR"
    assert params["cmd"] == "depart" and params["json"] == "y"


async def test_depart_none_uses_now():
    prov, seen = _provider(_json(TWO_TRIPS))
    out = await prov.route(SFO, EMBARCADERO, mode="bart")
    assert seen[0].url.params["date"] == "now" and seen[0].url.params["time"] == "now"
    assert "departure time not given, used BART 'now'" in out.run_report.warnings


async def test_multi_leg_transfer_warning():
    legs = [
        {"@order": "1", "@origin": "OAKL", "@destination": "COLS", "@line": "ROUTE 19",
         "@origTimeMin": "06:00 PM", "@origTimeDate": "10/27/2026",
         "@destTimeMin": "06:08 PM", "@destTimeDate": "10/27/2026"},
        {"@order": "2", "@origin": "COLS", "@destination": "EMBR", "@line": "ROUTE 3",
         "@origTimeMin": "06:12 PM", "@origTimeDate": "10/27/2026",
         "@destTimeMin": "06:35 PM", "@destTimeDate": "10/27/2026"},
    ]
    trip = _trip("06:00 PM", "06:35 PM", "35", legs=legs)
    prov, _ = _provider(_json(_payload([trip])))
    out = await prov.route(SFO, EMBARCADERO, mode="bart", depart_at=DEPART)
    leg = out.legs[0]
    assert leg.warnings == ["transfer at COLS"]
    assert leg.line == "ROUTE 19 + ROUTE 3"


async def test_transfer_uses_next_leg_origin():
    """Live OAKL quirk: leg 1 @destination is OAKL, the real transfer is leg 2 @origin."""
    legs = [
        {"@order": "1", "@origin": "OAKL", "@destination": "OAKL", "@line": "ROUTE 19",
         "@origTimeMin": "06:00 PM", "@origTimeDate": "10/27/2026",
         "@destTimeMin": "06:09 PM", "@destTimeDate": "10/27/2026"},
        {"@order": "2", "@origin": "COLS", "@destination": "EMBR", "@line": "ROUTE 11",
         "@origTimeMin": "06:17 PM", "@origTimeDate": "10/27/2026",
         "@destTimeMin": "06:36 PM", "@destTimeDate": "10/27/2026"},
    ]
    trip = _trip("06:00 PM", "06:36 PM", "36", legs=legs)
    prov, _ = _provider(_json(_payload([trip])))
    out = await prov.route(SFO, EMBARCADERO, mode="bart", depart_at=DEPART)
    assert out.legs[0].warnings == ["transfer at COLS"]
