"""Offline tests for the Google Hotels adapter (Bright Data mocked, fictional hotels)."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from decimal import Decimal

import httpx

from conferge.core.brightdata import BrightDataClient
from conferge.core.schemas import DiscoveryQuery, SourceRecord, SourceRef
from conferge.lodging._common import DATASET_GOOGLE_HOTELS
from conferge.lodging.google_hotels import (
    PROVIDER,
    GoogleHotelsSource,
    booking_options,
    to_lodging,
)
from conferge.lodging.models import LodgingQuery

NOW = datetime(2026, 10, 24, 18, 0, tzinfo=timezone.utc)
QUERY = LodgingQuery(check_in=date(2026, 10, 27), check_out=date(2026, 10, 30), adults=1,
                     currency="USD", limit=5)


def _row(hotel_id: str = "h-1", name: str = "Marina Fogline Inn", **extra) -> dict:
    row = {
        "url": f"https://www.google.com/travel/hotels/entity/{hotel_id}?ts=abc",
        "hotel_id": hotel_id, "hotel_name": name, "rating": 4.3, "review_count": "1,204",
        "address": "1 Fictional Way, San Francisco, CA", "check_in_date": "2026-10-27",
        "check_out_date": "2026-10-30", "guest_number": 1, "lat": 37.803, "long": -122.43,
        "currency": "USD", "booking_options": [],
    }
    row.update(extra)
    return row


def _record(row: dict) -> SourceRecord:
    return SourceRecord(provider=PROVIDER, source_id=str(row.get("hotel_id")),
                        source_mode="live", collected_at=NOW, source_url=row.get("url"),
                        request_id="snap-1", payload={"search": row})


def _source(handler, calls: list | None = None) -> GoogleHotelsSource:
    def wrapped(req: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append(req)
        return handler(req)

    http = httpx.AsyncClient(base_url="https://api.brightdata.com",
                             transport=httpx.MockTransport(wrapped))
    client = BrightDataClient("test-key", client=http, retries=0)
    return GoogleHotelsSource(client, poll_interval=0, max_wait=1, clock=lambda: NOW)


async def test_search_request_shape_and_records():
    calls: list[httpx.Request] = []
    rows = [_row("h-1"), _row("h-2", "Bay Lantern Hotel"), _row("h-1")]
    src = _source(lambda req: httpx.Response(200, json=rows), calls)
    result = await src.search(QUERY)
    req = calls[0]
    assert req.url.path == "/datasets/v3/scrape"
    assert req.url.params["dataset_id"] == DATASET_GOOGLE_HOTELS
    assert req.url.params["type"] == "discover_new"
    assert req.url.params["discover_by"] == "search"
    assert req.url.params["limit_per_input"] == "5"
    body = json.loads(req.content)
    assert body == {"input": [{
        "search_term": QUERY.search_term, "check_in_date": "2026-10-27",
        "check_out_date": "2026-10-30", "guest_number": 1, "country": "us", "currency": "USD",
    }]}
    assert [r.source_id for r in result.items] == ["h-1", "h-2"]
    rec = result.items[0]
    assert rec.source_mode == "live" and rec.collected_at == NOW
    assert str(rec.source_url) == rows[0]["url"]
    assert rec.payload["query"] == {"check_in": "2026-10-27", "check_out": "2026-10-30",
                                    "adults": 1, "currency": "USD"}
    assert rec.payload["dataset_id"] == DATASET_GOOGLE_HOTELS
    assert rec.content_hash and rec.content_hash.startswith("sha256:")
    assert result.run_report.status == "ok" and result.run_report.termination == "exhausted"
    assert result.run_report.fetched_count == 3 and result.run_report.unique_count == 2


async def test_rows_without_id_or_url_skipped_and_url_fallback():
    rows = [_row("h-1"), {"hotel_name": "Ghost Hotel"},
            {"hotel_name": "Url Only", "url": "https://www.google.com/travel/hotels/x?ts=1"}]
    result = await _source(lambda req: httpx.Response(200, json=rows)).search(QUERY)
    ids = [r.source_id for r in result.items]
    assert ids[0] == "h-1" and ids[1].startswith("url:")
    assert any("without hotel_id or url" in w for w in result.run_report.warnings)
    assert result.run_report.status == "degraded"


async def test_total_option_gives_quoted_total():
    row = _row(booking_options=[
        {"source": "Vendor A", "total_price": "$1,236 total", "link": "https://a.example/b"},
        {"source": "Vendor B", "price": "$1,500 for 3 nights", "link": "https://b.example/c"},
    ])
    lodging = to_lodging(_record(row), QUERY, now=NOW)
    assert lodging is not None
    assert lodging.price_status == "quoted_total"
    assert lodging.total_price == Decimal("1236.00")
    assert lodging.nightly_avg == Decimal("412.00")
    assert str(lodging.booking_url) == "https://a.example/b"
    assert lodging.lodging_type == "hotel" and lodging.rating == 4.3
    assert lodging.rating_scale == 5 and lodging.rating_count == 1204
    assert lodging.venue is not None and lodging.venue.coordinate_precision == "exact"


async def test_nightly_only_is_indicative():
    row = _row(booking_options=[{"vendor": "Vendor C", "rate_per_night": "$199",
                                 "url": "not-a-url"}])
    lodging = to_lodging(_record(row), QUERY, now=NOW)
    assert lodging.price_status == "indicative"
    assert lodging.total_price is None
    assert lodging.nightly_avg == Decimal("199.00")
    assert str(lodging.booking_url) == row["url"]


async def test_unqualified_and_zero_prices_are_unknown():
    row = _row(booking_options=[{"name": "Vendor D", "price": "$412"},
                                {"name": "Vendor E", "total_price": 0}])
    opts = booking_options(_record(row))
    assert opts[0]["raw_price_text"] == "$412"
    assert opts[0]["total"] is None and opts[0]["nightly"] is None
    assert all(o["total"] is None for o in opts)
    lodging = to_lodging(_record(row), QUERY, now=NOW)
    assert lodging.price_status == "unknown"
    assert lodging.total_price is None and lodging.nightly_avg is None


async def test_stay_mismatch_drops_price():
    row = _row(check_in_date="2026-10-28",
               booking_options=[{"source": "Vendor A", "total": "$900"}])
    warnings: list[str] = []
    lodging = to_lodging(_record(row), QUERY, warnings=warnings, now=NOW)
    assert lodging.price_status == "unknown" and lodging.total_price is None
    assert any("stay mismatch" in w for w in warnings)


async def test_never_verified_and_name_required():
    row = _row(booking_options=[{"source": "Vendor A", "total": "$900", "currency": "USD"}])
    assert to_lodging(_record(row), QUERY, now=NOW).price_status != "verified_bookable"
    assert to_lodging(_record(_row(hotel_name=None)), QUERY, now=NOW) is None


async def test_booking_options_keeps_several_vendors():
    row = _row(booking_options=[
        {"source": "Vendor A", "total_price": "$1,236", "link": "https://a.example/1"},
        {"seller": "Vendor B", "price_per_night": 420, "booking_link": "https://b.example/2"},
        "$1,300 total",
    ])
    opts = booking_options(_record(row))
    assert [o["vendor"] for o in opts] == ["Vendor A", "Vendor B", None]
    assert opts[0]["total"] == Decimal("1236")
    assert opts[1]["nightly"] == Decimal("420") and opts[1]["url"] == "https://b.example/2"
    assert opts[2]["total"] == Decimal("1300")


async def test_missing_key_fails_without_http():
    calls: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(req)
        return httpx.Response(200, json=[])

    http = httpx.AsyncClient(base_url="https://api.brightdata.com",
                             transport=httpx.MockTransport(handler))
    src = GoogleHotelsSource(BrightDataClient(None, client=http), clock=lambda: NOW)
    result = await src.search(QUERY)
    assert not calls
    assert result.run_report.status == "failed"
    assert any("missing_credentials" in e for e in result.run_report.errors)


async def test_rate_limited_and_blocked():
    res = await _source(lambda req: httpx.Response(429, json={})).search(QUERY)
    assert res.run_report.status == "failed" and res.run_report.termination == "rate_limited"
    res = await _source(lambda req: httpx.Response(403, json={})).search(QUERY)
    assert res.run_report.termination == "blocked"


async def test_page_cap_and_zero_results():
    rows = [_row(f"h-{i}") for i in range(QUERY.limit)]
    res = await _source(lambda req: httpx.Response(200, json=rows)).search(QUERY)
    assert res.run_report.termination == "page_cap" and res.run_report.status == "degraded"
    res = await _source(lambda req: httpx.Response(200, json=[])).search(QUERY)
    assert res.run_report.status == "degraded" and res.run_report.termination == "error"
    assert "zero results" in res.run_report.warnings


async def test_snapshot_pending_reports_id():
    res = await _source(
        lambda req: httpx.Response(202, json={"snapshot_id": "snap-9"})
        if req.url.path.endswith("/scrape") else httpx.Response(202, json={})
    ).search(QUERY)
    assert res.run_report.status == "failed" and res.run_report.termination == "error"
    assert any("snap-9" in w for w in res.run_report.warnings)


async def test_discover_without_dates_fails_cleanly():
    res = await _source(lambda req: httpx.Response(200, json=[])).discover(
        DiscoveryQuery(domain="lodging"))
    assert res.run_report.status == "failed"
    assert any("invalid lodging query" in e for e in res.run_report.errors)


async def test_fetch_details_collect_by_url():
    calls: list[httpx.Request] = []
    row = _row("h-7", "Crissy Dune Lodge")
    src = _source(lambda req: httpx.Response(200, json=[row]), calls)
    record = await src.fetch_details(SourceRef(provider=PROVIDER, source_id="h-7", url=row["url"]))
    assert "type" not in calls[0].url.params
    assert json.loads(calls[0].content) == {"input": [{"url": row["url"]}]}
    assert record.source_id == "h-7" and record.payload["detail"]["hotel_name"] == "Crissy Dune Lodge"
    assert to_lodging(record, QUERY, now=NOW) is not None
