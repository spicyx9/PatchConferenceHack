"""Offline tests for the Booking.com lodging source (Bright Data mocked with httpx)."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from conferge.core.brightdata import BrightDataClient
from conferge.core.schemas import DiscoveryQuery
from conferge.lodging._common import DATASET_BOOKING_DETAIL, DATASET_BOOKING_SEARCH
from conferge.lodging.booking import PROVIDER, BookingSource, stay_url, to_lodging
from conferge.lodging.models import LodgingQuery

T0 = datetime(2026, 10, 24, 9, 0, tzinfo=timezone.utc)
Q = LodgingQuery(check_in=date(2026, 10, 27), check_out=date(2026, 10, 30), adults=1,
                 currency="USD", verify_top=2)
PAGE = "https://www.booking.com/hotel/us/fictional-foghorn-inn.html"


def clock() -> datetime:
    return T0


def search_row(**over):
    row = {
        "url": PAGE + "?checkin=2026-10-27&checkout=2026-10-30&group_adults=1&no_rooms=1"
               "&group_children=&aid=999",
        "location": "San Francisco",
        "check_in": "2026-10-27T00:00:00.000Z",
        "check_out": "2026-10-30T00:00:00.000Z",
        "adults": 1, "children": "", "rooms": 1,
        "id": "900001", "title": "Fictional Foghorn Inn",
        "address": "1 Imaginary Pier", "city": "San Francisco",
        "review_score": 8.4, "review_count": "1,204",
        "final_price": 953, "original_price": 1100, "currency": "USD",
        "tax_description": "", "free_cancellation": True,
        "map_coordinates": {"lat": 37.805, "lon": -122.43},
        "property_type": "Hotel",
    }
    row.update(over)
    return row


def make_bd(handler):
    client = httpx.AsyncClient(base_url="https://api.brightdata.com",
                               transport=httpx.MockTransport(handler))
    return BrightDataClient("test-key", client=client, retries=0)


async def test_search_request_and_records():
    calls = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(req)
        return httpx.Response(200, json=[search_row(), search_row(), search_row(id=None)])

    src = BookingSource(make_bd(handler), clock=clock)
    res = await src.search(Q)
    req = calls[0]
    assert req.url.path == "/datasets/v3/scrape"
    assert req.url.params["dataset_id"] == DATASET_BOOKING_SEARCH
    assert "type" not in req.url.params and "discover_by" not in req.url.params
    assert "limit_per_input" not in req.url.params
    body = json.loads(req.content)["input"][0]
    assert body["check_in"] == "2026-10-27T00:00:00.000Z"
    assert body["check_out"] == "2026-10-30T00:00:00.000Z"
    assert body["url"] == "https://www.booking.com"
    assert (body["adults"], body["rooms"], body["currency"]) == (1, 1, "USD")

    rep = res.run_report
    assert rep.status == "ok" and rep.termination == "exhausted"
    assert rep.fetched_count == 3 and rep.unique_count == 1
    assert any("without id" in w for w in rep.warnings)
    rec = res.items[0]
    assert rec.provider == PROVIDER and rec.source_id == "900001"
    assert rec.source_mode == "live" and rec.collected_at == T0
    assert rec.payload["dataset_id"] == DATASET_BOOKING_SEARCH
    assert rec.payload["detail"] is None
    qs = parse_qs(urlsplit(str(rec.source_url)).query)
    assert qs["checkin"] == ["2026-10-27"] and qs["sb_price_type"] == ["total"]
    assert "aid" not in qs
    await src.aclose()


def test_stay_url():
    url = stay_url(PAGE + "?aid=1&label=x", Q)
    parts = urlsplit(url)
    assert parts.path == "/hotel/us/fictional-foghorn-inn.html"
    qs = parse_qs(parts.query, keep_blank_values=True)
    assert qs == {"checkin": ["2026-10-27"], "checkout": ["2026-10-30"], "group_adults": ["1"],
                  "no_rooms": ["1"], "group_children": ["0"], "selected_currency": ["USD"],
                  "sb_price_type": ["total"]}


def _record(row, detail=None, detail_at=None):
    from conferge.core.schemas import SourceRecord

    return SourceRecord(
        provider=PROVIDER, source_id=str(row["id"]), source_mode="live", collected_at=T0,
        source_url=stay_url(PAGE, Q),
        payload={"search": row, "detail": detail,
                 "detail_collected_at": detail_at.isoformat() if detail_at else None},
    )


def test_normalize_sample_like_row():
    lod = to_lodging(_record(search_row()), Q, now=T0)
    assert lod is not None
    assert lod.total_price == Decimal("953.00")
    assert lod.nightly_avg == Decimal("317.67")
    assert lod.base_total is None and lod.taxes is None and lod.fees_total is None
    assert lod.includes_all_fees is None
    assert lod.price_status == "quoted_total" and lod.availability == "unknown"
    assert lod.currency == "USD" and lod.rating == 8.4 and lod.rating_scale == 10
    assert lod.rating_count == 1204 and lod.free_cancellation is True
    assert lod.lodging_type == "hotel"
    assert lod.venue.latitude == 37.805 and lod.venue.coordinate_precision == "exact"


def test_zero_price_and_added_fees():
    lod = to_lodging(_record(search_row(final_price=0)), Q, now=T0)
    assert lod.total_price is None and lod.price_status == "unknown" and lod.currency is None
    lod = to_lodging(_record(search_row(tax_description="+ US$123 taxes and fees")), Q, now=T0)
    assert lod.fees_total == Decimal("123.00") and lod.taxes is None
    assert lod.includes_all_fees is False
    lod = to_lodging(_record(search_row(tax_description="Includes taxes and fees")), Q, now=T0)
    assert lod.includes_all_fees is True and lod.price_status == "quoted_total"
    assert to_lodging(_record(search_row(title="")), Q, now=T0) is None


def test_stay_mismatch_drops_price():
    warnings: list[str] = []
    row = search_row(check_out="2026-10-31T00:00:00.000Z")
    lod = to_lodging(_record(row), Q, warnings=warnings, now=T0)
    assert lod.total_price is None and lod.price_status == "unknown"
    assert any("stay mismatch" in w for w in warnings)


async def test_missing_key_no_http_call():
    calls = []

    def handler(req):
        calls.append(req)
        return httpx.Response(200, json=[])

    client = httpx.AsyncClient(base_url="https://api.brightdata.com",
                               transport=httpx.MockTransport(handler))
    src = BookingSource(BrightDataClient(None, client=client), clock=clock)
    res = await src.search(Q)
    assert res.items == [] and res.run_report.status == "failed"
    assert any("missing_credentials" in e for e in res.run_report.errors)
    records, rep = await src.verify([_record(search_row())], Q)
    assert rep.status == "failed" and records[0].payload["detail"] is None
    assert calls == []


async def test_http_403_blocked_and_429_rate_limited():
    src = BookingSource(make_bd(lambda req: httpx.Response(403, json={})), clock=clock)
    res = await src.search(Q)
    assert res.run_report.status == "failed" and res.run_report.termination == "blocked"
    src = BookingSource(make_bd(lambda req: httpx.Response(429, json={})), clock=clock)
    res = await src.search(Q)
    assert res.run_report.termination == "rate_limited"


async def test_snapshot_polling_ready():
    def handler(req):
        if req.url.path == "/datasets/v3/scrape":
            return httpx.Response(202, json={"snapshot_id": "s_fake1"})
        assert req.url.path == "/datasets/v3/snapshot/s_fake1"
        return httpx.Response(200, json=[search_row()])

    src = BookingSource(make_bd(handler), poll_interval=0, clock=clock)
    res = await src.search(Q)
    assert res.run_report.status == "ok" and res.items[0].request_id == "s_fake1"


async def test_snapshot_pending_reports_id():
    def handler(req):
        if req.url.path == "/datasets/v3/scrape":
            return httpx.Response(202, json={"snapshot_id": "s_slow"})
        return httpx.Response(202, json={"status": "running"})

    src = BookingSource(make_bd(handler), poll_interval=0, max_wait=0, clock=clock)
    res = await src.search(Q)
    assert res.run_report.status == "failed" and res.run_report.termination == "error"
    assert any("s_slow" in w for w in res.run_report.warnings)


async def test_page_cap_and_zero_results():
    rows = [search_row(id=str(i), total_listings_found=250) for i in range(3)]
    src = BookingSource(make_bd(lambda req: httpx.Response(200, json=rows)), clock=clock)
    rep = (await src.search(Q)).run_report
    assert rep.status == "degraded" and rep.termination == "page_cap"
    assert rep.expected_count == 250 and rep.unique_count == 3
    src = BookingSource(make_bd(lambda req: httpx.Response(200, json=[])), clock=clock)
    rep = (await src.search(Q)).run_report
    assert rep.status == "degraded" and rep.termination == "error"
    assert "zero results" in rep.warnings


async def test_discover_missing_dates_failed():
    src = BookingSource(make_bd(lambda req: httpx.Response(200, json=[])), clock=clock)
    res = await src.discover(DiscoveryQuery(domain="lodging", city="San Francisco"))
    assert res.run_report.status == "failed" and res.items == []


def detail_row(**over):
    row = {
        "url": "https://www.booking.com/hotel/us/fictional-foghorn-inn.en-gb.html",
        "listing_id": "900001", "title": "Fictional Foghorn Inn",
        "check_in": "2026-10-27", "check_out": "2026-10-30",
        "coordinates": {"latitude": 37.8051, "longitude": -122.4301},
        "full_address": "1 Imaginary Pier, San Francisco, CA",
        "availability": [{"room_type": "Queen Room", "available": True}],
        "pricing": [
            {"room_type": "Queen Room", "price": "US$1,010", "currency": "USD",
             "price_text": "Includes taxes and fees"},
            {"room_type": "King Room", "price": 1200, "currency": "USD",
             "taxes_included": True},
            {"room_type": "Bunk", "price": 300, "currency": "USD"},
        ],
    }
    row.update(over)
    return row


async def test_verify_attaches_detail_and_verified_bookable():
    calls = []
    other = search_row(id="900002", url="https://www.booking.com/hotel/us/made-up-lodge.html")

    def handler(req):
        calls.append(req)
        return httpx.Response(200, json=[detail_row()])

    src = BookingSource(make_bd(handler), clock=clock)
    records = [_record(search_row()), _record(other)]
    records[1] = records[1].model_copy(
        update={"source_url": stay_url("https://www.booking.com/hotel/us/made-up-lodge.html", Q)})
    out, rep = await src.verify(records, Q)
    assert calls[0].url.params["dataset_id"] == DATASET_BOOKING_DETAIL
    assert "limit_per_input" not in calls[0].url.params
    inputs = json.loads(calls[0].content)["input"]
    assert len(inputs) == 2 and "sb_price_type=total" in inputs[0]["url"]
    assert out[0].payload["detail"]["listing_id"] == "900001"
    assert out[0].payload["detail_collected_at"] == T0.isoformat()
    assert out[1].payload["detail"] is None
    assert rep.provider == "booking:verify" and rep.status == "degraded"
    assert rep.unique_count == 1

    lod = to_lodging(out[0], Q, now=T0 + timedelta(minutes=5))
    assert lod.price_status == "verified_bookable"
    assert lod.total_price == Decimal("1010.00") and lod.includes_all_fees is True
    assert lod.availability == "verified_available" and lod.verified_at == T0
    assert lod.venue.latitude == 37.8051
    assert any(e.raw_ref == DATASET_BOOKING_DETAIL for e in lod.evidence)

    stale = to_lodging(out[0], Q, now=T0 + timedelta(minutes=31))
    assert stale.price_status == "quoted_total"


def test_detail_unavailable_and_mismatch():
    rec = _record(search_row(), detail_row(availability=[]), T0)
    assert to_lodging(rec, Q, now=T0).price_status == "unavailable"
    rec = _record(search_row(), detail_row(availability="Sold out"), T0)
    assert to_lodging(rec, Q, now=T0).availability == "unavailable"
    warnings: list[str] = []
    rec = _record(search_row(), detail_row(check_in="2026-10-28"), T0)
    lod = to_lodging(rec, Q, warnings=warnings, now=T0)
    assert lod.price_status == "quoted_total" and lod.total_price == Decimal("953.00")
    assert warnings


def test_detail_without_taxes_signal_keeps_search_quote():
    rec = _record(search_row(), detail_row(pricing=[{"price": 500, "currency": "USD"}]), T0)
    lod = to_lodging(rec, Q, now=T0)
    assert lod.price_status == "quoted_total" and lod.total_price == Decimal("953.00")
    assert lod.availability == "verified_available"


async def test_fetch_details():
    def handler(req):
        return httpx.Response(200, json=[detail_row()])

    from conferge.core.schemas import SourceRef

    src = BookingSource(make_bd(handler), clock=clock)
    rec = await src.fetch_details(SourceRef(provider=PROVIDER, source_id="900001",
                                            url=stay_url(PAGE, Q)))
    assert rec.payload["detail"]["listing_id"] == "900001"
    assert to_lodging(rec, Q, now=T0).price_status == "verified_bookable"
    with pytest.raises(ValueError):
        await src.fetch_details(SourceRef(provider=PROVIDER, source_id="x", url=PAGE))
