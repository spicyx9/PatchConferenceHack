"""Offline tests for the Airbnb adapter (fake pyairbnb module, httpx.MockTransport for BD).

Rows below are trimmed copies of raw/lodging/pyairbnb-search-first-page.json (live capture,
pyairbnb 2.2.2, Fort Mason bbox, 2026-10-27..30, 1 adult, USD).
"""

from __future__ import annotations

import copy
import time
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

import httpx
import pytest

from conferge.core.brightdata import BrightDataClient
from conferge.core.schemas import DiscoveryQuery, SourceRef
from conferge.lodging import airbnb
from conferge.lodging.airbnb import (
    AirbnbError,
    AirbnbSource,
    BrightDataAirbnbBackend,
    PyAirbnbBackend,
    room_url,
    to_lodging,
)
from conferge.lodging.models import LodgingQuery

T0 = datetime(2026, 10, 24, 18, 0, tzinfo=timezone.utc)

HOTEL_ZOE = {  # FEATURED_HOTEL with Resort fee line
    "room_id": 1681202052912791908,
    "name": "Hotel Zoe Fisherman's Wharf, Deluxe king",
    "title": "Hotel Zoe Fisherman's Wharf",
    "paymentMessages": [{"text": "Free cancellation", "type": "FREE_CANCELLATION"}],
    "fee": {"airbnb": {}, "cleaning": {}},
    "price": {
        "unit": {"qualifier": ""},
        "total": {"currency_symbol": "", "amount": 0},
        "break_down": [
            {"description": "3 nights x $299.47", "amount": 898.4, "currency": "$"},
            {"description": "Resort fee", "amount": 123.6, "currency": "$"},
        ],
    },
    "rating": {"value": 4.6, "reviewCount": "1,024"},
    "badges": ["FEATURED_HOTEL"],
    "coordinates": {"latitude": 37.8066, "longitud": -122.4166},
}
CAPSULE = {  # long stay discount + "Price after discount" summary line
    "room_id": 1435622950408243449,
    "name": "Single Bed in 6 Bed Male Capsule Room with Shared Bath",
    "title": "Shared hotel room in San Francisco",
    "paymentMessages": [],
    "fee": {"airbnb": {}, "cleaning": {}},
    "price": {
        "unit": {"qualifier": "for 3 nights", "curency_symbol": "$", "amount": 133.0,
                 "discount": 107.0},
        "total": {"currency_symbol": "", "amount": 0},
        "break_down": [
            {"description": "3 nights x $44.28", "amount": 132.84, "currency": "$"},
            {"description": "Long stay discount", "amount": -26.57, "currency": "$"},
            {"description": "Price after discount", "amount": 106.27, "currency": "$"},
        ],
    },
    "rating": {"value": 4.2, "reviewCount": "88"},
    "badges": [],
    "coordinates": {"latitude": 37.79, "longitud": -122.41},
}
INNER_RICHMOND = {  # private room, the room checked with get_price / get_calendar
    "room_id": 20906522,
    "name": "311B Private Room in Super Convenient Area",
    "title": "Room in Inner Richmond",
    "paymentMessages": [],
    "fee": {"airbnb": {}, "cleaning": {}},
    "price": {
        "unit": {"qualifier": "for 3 nights", "curency_symbol": "$", "amount": 349.0,
                 "discount": 292.0},
        "total": {"currency_symbol": "", "amount": 0},
        "break_down": [{"description": "3 nights x $97.33", "amount": 292.0, "currency": "$"}],
    },
    "rating": {"value": 4.85, "reviewCount": "412"},
    "badges": ["SUPERHOST"],
    "coordinates": {"latitude": 37.78, "longitud": -122.46},
}
GET_PRICE = {"raw": [], "main": {"price": "$292", "discountedPrice": "$292",
                                 "originalPrice": "$349", "qualifier": "for 3 nights",
                                 "details": {"3 nights x $97.33": "$292.00"}}}


def _day(d: str, available: bool, checkin: bool = True, checkout: bool = True,
         min_n: int = 1, max_n: int = 14) -> dict[str, Any]:
    return {"__typename": "MerlinCalendarDay", "calendarDate": d, "available": available,
            "maxNights": max_n, "minNights": min_n, "availableForCheckin": checkin,
            "availableForCheckout": checkout, "bookable": available}


# Same values as raw/lodging/pyairbnb-calendar.json for 2026-10-26..31.
CALENDAR = [{"month": 10, "year": 2026, "days": [
    _day("2026-10-26", True), _day("2026-10-27", True), _day("2026-10-28", True),
    _day("2026-10-29", True), _day("2026-10-30", True),
    _day("2026-10-31", False, checkin=False),
]}]


def Q(**kw: Any) -> LodgingQuery:
    return LodgingQuery(check_in=date(2026, 10, 27), check_out=date(2026, 10, 30), **kw)


class FakePyAirbnb:
    def __init__(self, rows: Any = None, *, delay: float = 0.0, exc: Exception | None = None,
                 calendar: Any = None) -> None:
        self.rows = [copy.deepcopy(r) for r in (rows or [])] if isinstance(rows, list) else rows
        self.delay, self.exc = delay, exc
        self.calendar = CALENDAR if calendar is None else calendar
        self.calls: list[tuple[str, tuple, dict]] = []

    def search_all(self, *args: Any, **kwargs: Any) -> Any:
        self.calls.append(("search_all", args, kwargs))
        if self.delay:
            time.sleep(self.delay)
        if self.exc:
            raise self.exc
        return self.rows

    def get_price(self, room_id: str, check_in: date, check_out: date, **kwargs: Any) -> dict:
        self.calls.append(("get_price", (room_id, check_in, check_out), kwargs))
        if room_id == str(HOTEL_ZOE["room_id"]):
            raise RuntimeError("Not corret status code: 500")
        return copy.deepcopy(GET_PRICE)

    def get_api_key(self, proxy_url: str) -> str:
        return "fake-key"

    def get_calendar(self, api_key: str = "", room_id: str = "", **_: Any) -> list:
        self.calls.append(("get_calendar", (), {"room_id": room_id}))
        return copy.deepcopy(self.calendar)

    def get_details(self, room_id: int | None = None, **kwargs: Any) -> dict:
        return {"room_id": room_id, "title": "Room in Inner Richmond"}


class MissingBackend(PyAirbnbBackend):
    def _load(self) -> Any:
        raise ImportError("No module named 'pyairbnb'")


class StubFallback:
    name = "brightdata"

    def __init__(self) -> None:
        self.calls = 0

    async def search(self, q: LodgingQuery):
        self.calls += 1
        return await BrightDataAirbnbBackend(_bd_client(BD_ROWS), clock=lambda: T0).search(q)

    async def enrich(self, records, q):
        return list(records), []


BD_ROWS = [
    {"property_id": "777001", "listing_title": "Marina Garden Studio", "name": "Studio",
     "listing_name": "Entire rental unit in San Francisco", "price": 180, "total_price": 612,
     "currency": "USD", "availability": "true", "lat": 37.80, "long": -122.43,
     "is_exact_location": False, "ratings": 4.9, "property_number_of_reviews": 52,
     "travel_details": {"check_in": "2026-10-27T00:00:00.000Z",
                        "check_out": "2026-10-30T00:00:00.000Z", "num_of_adults": 1},
     "reviews": ["x" * 500]},
    {"property_id": "777002", "listing_title": "Nob Hill Loft", "price": 150,
     "total_price": None, "currency": "USD", "availability": "false", "lat": 37.79,
     "long": -122.41, "is_exact_location": True, "ratings": 4.5,
     "property_number_of_reviews": 10,
     "travel_details": {"check_in": None, "check_out": None, "num_of_adults": 1}},
    {"property_id": "777003", "listing_title": "Dorm bed at Green Tortoise Hostel",
     "price": None, "total_price": 300, "currency": "USD", "availability": "false",
     "travel_details": {"check_in": "2026-10-27T00:00:00.000Z",
                        "check_out": "2026-10-30T00:00:00.000Z", "num_of_adults": 1}},
]


def _bd_client(rows: list[dict[str, Any]], seen: list[httpx.Request] | None = None):
    def handler(req: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(req)
        return httpx.Response(200, json=rows)

    http = httpx.AsyncClient(base_url="https://api.brightdata.com",
                             transport=httpx.MockTransport(handler))
    return BrightDataClient("test-key", client=http)


def _source(module: Any, fallback: Any = None, **kw: Any) -> AirbnbSource:
    return AirbnbSource(PyAirbnbBackend(module, clock=lambda: T0, **kw),
                        fallback or StubFallback(), clock=lambda: T0)


# ---------------------------------------------------------------- pure helpers


def test_room_url_prefills_stay():
    assert room_url("20906522", Q()) == (
        "https://www.airbnb.com/rooms/20906522?check_in=2026-10-27&check_out=2026-10-30"
        "&adults=1&currency=USD")


async def test_search_breakdown_sum_resort_fee_and_discount():
    mod = FakePyAirbnb([HOTEL_ZOE, CAPSULE, INNER_RICHMOND])
    res = await _source(mod).search(Q())
    assert res.run_report.status == "ok" and res.run_report.termination == "exhausted"
    by_id = {r.source_id: r for r in res.items}
    rec = by_id[str(HOTEL_ZOE["room_id"])]
    assert rec.payload["backend"] == "pyairbnb" and rec.source_mode == "live"
    assert rec.collected_at == T0 and rec.payload["market_context"]["country"] == "us"
    warnings: list[str] = []
    zoe = to_lodging(rec, Q(), warnings=warnings, now=T0)
    assert zoe.total_price == Decimal("1022.00")  # 898.40 + 123.60 resort fee
    assert zoe.base_total == Decimal("898.40") and zoe.fees_total == Decimal("123.60")
    assert zoe.taxes is None and zoe.includes_all_fees is None
    assert zoe.nightly_avg == Decimal("340.67") and zoe.price_status == "quoted_total"
    assert zoe.lodging_type == "hotel" and zoe.free_cancellation is True
    assert zoe.venue.coordinate_precision == "approximate"
    assert zoe.venue.longitude == pytest.approx(-122.4166)
    assert zoe.rating == 4.6 and zoe.rating_scale == 5 and zoe.rating_count == 1024
    assert str(zoe.booking_url).startswith("https://www.airbnb.com/rooms/1681202052912791908?")

    cap = to_lodging(by_id[str(CAPSULE["room_id"])], Q(), now=T0)
    # 132.84 - 26.57; the "Price after discount" summary line is not added again.
    assert cap.total_price == Decimal("106.27") and cap.fees_total is None
    assert cap.lodging_type == "hotel" and cap.free_cancellation is None


def _pyrecord(row: dict[str, Any], **payload: Any):
    from conferge.core.schemas import SourceRecord

    base = airbnb._payload("pyairbnb", copy.deepcopy(row), Q())
    base.update(payload)
    return SourceRecord(provider="airbnb", source_id=str(row["room_id"]), source_mode="live",
                        collected_at=T0, payload=base)


def test_total_amount_zero_never_used_and_payable_at_property():
    row = copy.deepcopy(HOTEL_ZOE)
    row["price"]["break_down"] = []
    lod = to_lodging(_pyrecord(row), Q(), now=T0)
    assert lod.total_price is None and lod.price_status == "unknown"
    row = copy.deepcopy(HOTEL_ZOE)
    row["price"]["break_down"][1]["description"] = "Resort fee (payable at property)"
    lod = to_lodging(_pyrecord(row), Q(), now=T0)
    assert lod.total_price == Decimal("898.40") and lod.payable_at_property == Decimal("123.60")
    assert lod.fees_total is None


def test_nights_mismatch_drops_price():
    row = copy.deepcopy(INNER_RICHMOND)
    row["price"]["break_down"][0]["description"] = "2 nights x $146.00"
    warnings: list[str] = []
    lod = to_lodging(_pyrecord(row), Q(), warnings=warnings, now=T0)
    assert lod.total_price is None and lod.price_status == "unknown"
    assert any("2 nights" in w for w in warnings)


def test_unit_qualifier_without_breakdown_uses_discounted_amount():
    row = copy.deepcopy(INNER_RICHMOND)
    row["price"]["break_down"] = []
    lod = to_lodging(_pyrecord(row), Q(), now=T0)
    assert lod.total_price == Decimal("292.00") and lod.price_status == "quoted_total"


def test_hostel_and_apartment_types():
    dorm = copy.deepcopy(INNER_RICHMOND)
    dorm["name"] = "Female 4 Bed Dormitory at Social SF Hostel"
    assert to_lodging(_pyrecord(dorm), Q(), now=T0).lodging_type == "hostel"
    assert to_lodging(_pyrecord(INNER_RICHMOND), Q(), now=T0).lodging_type == "apartment"


def test_calendar_verified_available_but_never_verified_bookable():
    days = airbnb._stay_days(CALENDAR, Q())
    assert [d["calendarDate"] for d in days] == [
        "2026-10-27", "2026-10-28", "2026-10-29", "2026-10-30"]
    rec = _pyrecord(INNER_RICHMOND, price_check=GET_PRICE, price_checked_at=T0.isoformat(),
                    calendar=days, calendar_checked_at=T0.isoformat())
    lod = to_lodging(rec, Q(), now=T0)
    assert lod.availability == "verified_available"
    assert lod.price_status == "quoted_total"  # taxes never exposed: never verified_bookable
    assert lod.total_price == Decimal("292.00") and lod.verified_at is None


def test_calendar_unavailable_and_unknown():
    blocked = [_day("2026-10-27", True), _day("2026-10-28", False), _day("2026-10-29", True)]
    lod = to_lodging(_pyrecord(INNER_RICHMOND, calendar=blocked), Q(), now=T0)
    assert lod.availability == "unavailable" and lod.price_status == "unavailable"
    min_nights = [_day("2026-10-27", True, min_n=5), _day("2026-10-28", True),
                  _day("2026-10-29", True)]
    lod = to_lodging(_pyrecord(INNER_RICHMOND, calendar=min_nights), Q(), now=T0)
    assert lod.availability == "unknown"


def test_price_check_nights_mismatch_is_ignored():
    check = copy.deepcopy(GET_PRICE)
    check["main"]["qualifier"] = "for 2 nights"
    check["main"]["discountedPrice"] = "$999"
    warnings: list[str] = []
    lod = to_lodging(_pyrecord(INNER_RICHMOND, price_check=check,
                               price_checked_at=T0.isoformat()), Q(), warnings=warnings, now=T0)
    assert lod.total_price == Decimal("292.00")
    assert any("get_price is for 2 nights" in w for w in warnings)


# ---------------------------------------------------------------- search and fallback


async def test_search_dedup_and_truncation_warning():
    mod = FakePyAirbnb([HOTEL_ZOE, CAPSULE, INNER_RICHMOND, HOTEL_ZOE])
    res = await _source(mod).search(Q(limit=2))
    rep = res.run_report
    assert len(res.items) == 2 and rep.fetched_count == 4 and rep.unique_count == 3
    assert rep.status == "ok" and any("kept 2 of 3" in w for w in rep.warnings)
    name, args, kwargs = mod.calls[0]
    assert name == "search_all" and args[:2] == ("2026-10-27", "2026-10-30")
    assert args[6:9] == (14, 0, 0) and kwargs == {"adults": 1, "currency": "USD"}
    ne_lat, ne_lng, sw_lat, sw_lng = args[2:6]
    assert ne_lat > 37.806 > sw_lat and ne_lng > -122.432 > sw_lng


async def test_fallback_on_dependency_missing():
    fb = StubFallback()
    src = AirbnbSource(MissingBackend(clock=lambda: T0), fb, clock=lambda: T0)
    res = await src.search(Q())
    assert fb.calls == 1 and res.run_report.provider == "airbnb"
    assert res.items and res.items[0].payload["backend"] == "brightdata"
    assert res.run_report.source_mode == "live"
    assert "dependency_missing: pyairbnb" in res.run_report.warnings[0]
    assert "switched to brightdata" in res.run_report.warnings[0]


async def test_fallback_on_timeout():
    fb = StubFallback()
    src = _source(FakePyAirbnb([HOTEL_ZOE], delay=0.3), fb, timeout=0.05)
    res = await src.search(Q())
    assert fb.calls == 1 and "timeout" in res.run_report.warnings[0]


async def test_fallback_on_schema_error():
    fb = StubFallback()
    res = await _source(FakePyAirbnb({"oops": 1}), fb).search(Q())
    assert fb.calls == 1 and "schema_changed" in res.run_report.warnings[0]
    fb2 = StubFallback()
    await _source(FakePyAirbnb([{"id": 1, "name": "x"}]), fb2).search(Q())
    assert fb2.calls == 1


async def test_fallback_when_no_row_has_price():
    rows = [copy.deepcopy(HOTEL_ZOE), copy.deepcopy(INNER_RICHMOND)]
    for r in rows:
        r["price"] = {"unit": {"qualifier": ""}, "total": {"amount": 0}, "break_down": []}
    fb = StubFallback()
    res = await _source(FakePyAirbnb(rows), fb).search(Q())
    assert fb.calls == 1 and "price_fields_absent" in res.run_report.warnings[0]


async def test_fallback_on_block():
    fb = StubFallback()
    res = await _source(FakePyAirbnb(exc=RuntimeError("Not corret status code: 403")), fb
                        ).search(Q())
    assert fb.calls == 1 and "blocked" in res.run_report.warnings[0]


async def test_no_fallback_on_zero_results():
    fb = StubFallback()
    res = await _source(FakePyAirbnb([]), fb).search(Q())
    assert fb.calls == 0 and res.items == []
    rep = res.run_report
    assert rep.status == "degraded" and rep.termination == "error"
    assert any("zero results" in w for w in rep.warnings)


# ---------------------------------------------------------------- verify


async def test_verify_enriches_top_and_reports_per_room_failures():
    mod = FakePyAirbnb([INNER_RICHMOND, HOTEL_ZOE, CAPSULE])
    src = _source(mod)
    res = await src.search(Q())
    out, rep = await src.verify(res.items, Q(verify_top=2))
    assert rep.provider == "airbnb" and rep.termination == "not_applicable"
    assert rep.status == "degraded" and any("get_price failed" in w for w in rep.warnings)
    by_id = {r.source_id: r for r in out}
    ir = by_id["20906522"].payload
    assert ir["price_check"]["main"]["discountedPrice"] == "$292"
    assert len(ir["calendar"]) == 4 and ir["calendar_checked_at"]
    assert by_id[str(CAPSULE["room_id"])].payload["price_check"] is None  # beyond verify_top
    lod = to_lodging(by_id["20906522"], Q(), now=T0)
    assert lod.availability == "verified_available" and lod.price_status == "quoted_total"
    priced = [c for c in mod.calls if c[0] == "get_price"]
    assert len(priced) == 2 and priced[0][1][1] == date(2026, 10, 27)


async def test_verify_caps_at_ten():
    rows = []
    for i in range(12):
        r = copy.deepcopy(INNER_RICHMOND)
        r["room_id"] = 1000 + i
        rows.append(r)
    mod = FakePyAirbnb(rows)
    src = _source(mod)
    res = await src.search(Q())
    await src.verify(res.items, Q(verify_top=50))
    assert len([c for c in mod.calls if c[0] == "get_price"]) == 10


# ---------------------------------------------------------------- Bright Data


async def test_bd_missing_key_is_failed_missing_credentials():
    client = BrightDataClient(None, client=httpx.AsyncClient())
    res = await BrightDataAirbnbBackend(client, clock=lambda: T0).search(Q())
    assert res.run_report.status == "failed" and res.items == []
    assert res.run_report.errors[0].startswith("missing_credentials")


async def test_bd_rows_normalization():
    seen: list[httpx.Request] = []
    backend = BrightDataAirbnbBackend(_bd_client(BD_ROWS, seen), clock=lambda: T0)
    res = await backend.search(Q())
    assert res.run_report.status == "ok" and len(res.items) == 3
    req = seen[0]
    assert req.url.params["discover_by"] == "location"
    assert req.url.params["dataset_id"] == "gd_ld7ll037kqy322v05"
    assert b'"check_in":"2026-10-27T00:00:00.000Z"' in req.content.replace(b" ", b"")
    by_id = {r.source_id: r for r in res.items}
    assert "reviews" not in by_id["777001"].payload["search"]
    assert by_id["777001"].payload["backend"] == "brightdata"

    marina = to_lodging(by_id["777001"], Q(), now=T0)
    assert marina.total_price == Decimal("612.00") and marina.price_status == "quoted_total"
    assert marina.availability == "unknown" and marina.lodging_type == "apartment"
    assert marina.venue.coordinate_precision == "approximate" and marina.rating_count == 52

    loft = to_lodging(by_id["777002"], Q(), now=T0)  # no date echo: per-night is indicative
    assert loft.total_price is None and loft.price_status == "indicative"
    assert loft.nightly_avg == Decimal("150.00") and loft.availability == "unknown"
    assert loft.venue.coordinate_precision == "exact"

    dorm = to_lodging(by_id["777003"], Q(), now=T0)  # dates echoed + availability false
    assert dorm.availability == "unavailable" and dorm.price_status == "unavailable"
    assert dorm.lodging_type == "hostel"


async def test_bd_other_dates_echo_drops_price():
    row = copy.deepcopy(BD_ROWS[0])
    row["travel_details"] = {"check_in": "2024-12-20T00:00:00.000Z",
                             "check_out": "2024-12-30T00:00:00.000Z", "num_of_adults": 2}
    row["availability"] = "false"
    res = await BrightDataAirbnbBackend(_bd_client([row]), clock=lambda: T0).search(Q())
    warnings: list[str] = []
    lod = to_lodging(res.items[0], Q(), warnings=warnings, now=T0)
    assert lod.total_price is None and lod.nightly_avg is None
    assert lod.availability == "unknown" and warnings


# ---------------------------------------------------------------- discover / details


async def test_discover_and_fetch_details():
    src = _source(FakePyAirbnb([INNER_RICHMOND]))
    res = await src.discover(Q().to_discovery())
    assert len(res.items) == 1
    bad = await src.discover(DiscoveryQuery(domain="lodging", city="San Francisco"))
    assert bad.run_report.status == "failed" and "invalid_query" in bad.errors[0]
    rec = await src.fetch_details(SourceRef(provider="airbnb", source_id="20906522"))
    assert rec.payload["details"]["room_id"] == 20906522 and rec.source_mode == "live"
    with pytest.raises(AirbnbError):
        await src.fetch_details(SourceRef(provider="airbnb", source_id="abc"))
    missing = AirbnbSource(MissingBackend(clock=lambda: T0), StubFallback(), clock=lambda: T0)
    with pytest.raises(AirbnbError, match="dependency_missing"):
        await missing.fetch_details(SourceRef(provider="airbnb", source_id="20906522"))
