"""Offline tests for LumaSource: pagination, cursor loops, drift, dedup, timezone."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from conferge.core.brightdata import BrightDataClient
from conferge.core.schemas import DiscoveryQuery, Event, SourceRef
from conferge.events.luma import LumaError, LumaSource, load_fixture, normalize, run

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "luma.json"


async def _nosleep(_: float) -> None:
    return None


def _entry(api_id: str, start: str = "2026-10-28T01:00:00.000Z", **event: object) -> dict:
    ev = {
        "api_id": api_id, "name": f"Event {api_id}", "start_at": start,
        "end_at": "2026-10-28T04:00:00.000Z", "timezone": "America/Los_Angeles",
        "url": f"slug-{api_id}", "visibility": "public",
        "coordinate": {"latitude": 37.8060, "longitude": -122.4320},
        "geo_address_info": {"mode": "shown", "city": "San Francisco",
                             "address": "2 Marina Blvd",
                             "full_address": "2 Marina Blvd, San Francisco, CA 94123, USA"},
        "geo_address_visibility": "public",
    }
    ev.update(event)
    return {"api_id": api_id, "event": ev, "hosts": [{"api_id": "usr-1", "name": "Host One"}],
            "calendar": {"api_id": "cal-1", "name": "Dev Calendar", "is_personal": False},
            "guest_count": 42,
            "ticket_info": {"is_free": False, "is_sold_out": False,
                            "price": {"cents": 2500, "min_cents": 2000, "currency": "usd"},
                            "max_price": None}}


def _source(handler, **kw) -> tuple[LumaSource, list[dict]]:
    calls: list[dict] = []

    def wrapped(request: httpx.Request) -> httpx.Response:
        params = {k: v[0] for k, v in parse_qs(urlparse(str(request.url)).query).items()}
        calls.append(params)
        return handler(request, params, len(calls))

    client = httpx.AsyncClient(transport=httpx.MockTransport(wrapped))
    return LumaSource(client=client, sleep=_nosleep, **kw), calls


QUERY = DiscoveryQuery(domain="events", latitude=37.806, longitude=-122.432, limit=1000)


async def test_three_pages_then_exhausted_uses_pagination_cursor() -> None:
    pages = {
        None: {"entries": [_entry("evt-1"), _entry("evt-2")], "has_more": True, "next_cursor": "c1"},
        "c1": {"entries": [_entry("evt-3")], "has_more": True, "next_cursor": "c2"},
        "c2": {"entries": [_entry("evt-4")], "has_more": False, "next_cursor": None},
    }
    src, calls = _source(lambda r, p, n: httpx.Response(200, json=pages[p.get("pagination_cursor")]))
    result = await src.discover(QUERY)
    rep = result.run_report
    assert (rep.status, rep.termination, rep.pages) == ("ok", "exhausted", 3)
    assert rep.fetched_count == rep.unique_count == 4
    assert [c.get("pagination_cursor") for c in calls] == [None, "c1", "c2"]
    assert all("cursor" not in c and "slug" not in c for c in calls)
    assert all(c["pagination_limit"] == "50" for c in calls)
    rec = result.items[0]
    assert rec.source_mode == "live" and rec.collected_at.tzinfo is not None
    assert rec.payload["event"]["api_id"] == "evt-1"  # raw payload preserved
    assert str(rec.source_url) == "https://luma.com/slug-evt-1"
    assert rec.content_hash and rec.content_hash.startswith("sha256:")


async def test_repeated_cursor_is_cursor_stuck_degraded() -> None:
    def handler(r, p, n):
        return httpx.Response(200, json={"entries": [_entry(f"evt-{n}")], "has_more": True,
                                         "next_cursor": "same"})
    src, calls = _source(handler)
    rep = (await src.discover(QUERY)).run_report
    assert (rep.status, rep.termination) == ("degraded", "cursor_stuck")
    assert len(calls) == 2


async def test_has_more_without_new_ids_is_cursor_stuck() -> None:
    def handler(r, p, n):
        return httpx.Response(200, json={"entries": [_entry("evt-1")], "has_more": True,
                                         "next_cursor": f"c{n}"})
    src, _ = _source(handler)
    result = await src.discover(QUERY)
    assert result.run_report.termination == "cursor_stuck"
    assert result.run_report.status == "degraded"
    assert result.run_report.unique_count == 1 and result.run_report.fetched_count == 2


async def test_zero_page_with_has_more_true_is_not_exhausted() -> None:
    src, _ = _source(lambda r, p, n: httpx.Response(
        200, json={"entries": [], "has_more": True, "next_cursor": "c1"}))
    rep = (await src.discover(QUERY)).run_report
    assert rep.termination == "cursor_stuck" and rep.status == "degraded"


async def test_zero_results_exhausted_is_ok_with_warning() -> None:
    src, _ = _source(lambda r, p, n: httpx.Response(200, json={"entries": [], "has_more": False}))
    rep = (await src.discover(QUERY)).run_report
    assert (rep.status, rep.termination, rep.fetched_count) == ("ok", "exhausted", 0)
    assert any("zero results" in w for w in rep.warnings)


async def test_page_cap() -> None:
    def handler(r, p, n):
        return httpx.Response(200, json={"entries": [_entry(f"evt-{n}")], "has_more": True,
                                         "next_cursor": f"c{n}"})
    src, calls = _source(handler, max_pages=3)
    rep = (await src.discover(QUERY)).run_report
    assert (rep.status, rep.termination, rep.pages, len(calls)) == ("degraded", "page_cap", 3, 3)


async def test_changed_json_schema_first_page_is_failed() -> None:
    src, _ = _source(lambda r, p, n: httpx.Response(200, json={"events": [], "more": False}))
    result = await src.discover(QUERY)
    assert (result.run_report.status, result.run_report.termination) == ("failed", "schema_changed")
    assert result.items == [] and result.errors


async def test_html_instead_of_json_mid_run_is_degraded() -> None:
    def handler(r, p, n):
        if n == 1:
            return httpx.Response(200, json={"entries": [_entry("evt-1")], "has_more": True,
                                             "next_cursor": "c1"})
        return httpx.Response(200, text="<html>challenge</html>")
    src, _ = _source(handler)
    result = await src.discover(QUERY)
    assert (result.run_report.status, result.run_report.termination) == ("degraded", "schema_changed")
    assert len(result.items) == 1


async def test_entry_without_api_id_is_skipped_with_warning() -> None:
    bad = {"event": {"name": "no id"}}
    src, _ = _source(lambda r, p, n: httpx.Response(
        200, json={"entries": [bad, _entry("evt-1")], "has_more": False}))
    result = await src.discover(QUERY)
    assert [r.source_id for r in result.items] == ["evt-1"]
    assert any("without api_id" in w for w in result.run_report.warnings)


async def test_duplicate_ids_across_pages_are_deduped() -> None:
    pages = {
        None: {"entries": [_entry("evt-1"), _entry("evt-2")], "has_more": True, "next_cursor": "c1"},
        "c1": {"entries": [_entry("evt-2"), _entry("evt-3")], "has_more": False},
    }
    src, _ = _source(lambda r, p, n: httpx.Response(200, json=pages[p.get("pagination_cursor")]))
    result = await src.discover(QUERY)
    assert result.run_report.fetched_count == 4 and result.run_report.unique_count == 3
    assert sorted(r.source_id for r in result.items) == ["evt-1", "evt-2", "evt-3"]


async def test_403_without_unlocker_is_blocked_failed() -> None:
    src, calls = _source(lambda r, p, n: httpx.Response(403, text="nope"))
    result = await src.discover(QUERY)
    assert (result.run_report.status, result.run_report.termination) == ("failed", "blocked")
    assert len(calls) == 1  # 403 is not retried directly


async def test_429_persistent_is_rate_limited_after_retries() -> None:
    src, calls = _source(lambda r, p, n: httpx.Response(429))
    rep = (await src.discover(QUERY)).run_report
    assert (rep.status, rep.termination, len(calls)) == ("failed", "rate_limited", 3)


async def test_403_retries_via_web_unlocker_when_configured() -> None:
    body = json.dumps({"entries": [_entry("evt-1")], "has_more": False})

    def bd_handler(request: httpx.Request) -> httpx.Response:
        assert json.loads(request.content)["zone"] == "unlocker"
        return httpx.Response(200, text=body)

    bd = BrightDataClient("test-key", unlocker_zone="unlocker",
                          client=httpx.AsyncClient(base_url="https://api.brightdata.com",
                                                   transport=httpx.MockTransport(bd_handler)))
    src, _ = _source(lambda r, p, n: httpx.Response(403), brightdata=bd)
    rep = (await src.discover(QUERY)).run_report
    assert (rep.status, rep.termination) == ("ok", "exhausted")
    assert any("Web Unlocker" in w for w in rep.warnings)


async def test_date_window_uses_local_date_and_radius() -> None:
    entries = [
        # 2026-10-27T06:30Z is 23:30 on Oct 26 in Los Angeles -> outside the 27..30 window
        _entry("evt-late26", start="2026-10-27T06:30:00.000Z", end_at="2026-10-27T06:50:00.000Z"),
        _entry("evt-in", start="2026-10-28T01:00:00.000Z"),
        _entry("evt-far", start="2026-10-28T01:00:00.000Z",
               coordinate={"latitude": 37.3382, "longitude": -121.8863}),  # San Jose
    ]
    src, _ = _source(lambda r, p, n: httpx.Response(200, json={"entries": entries, "has_more": False}))
    query = DiscoveryQuery(domain="events", latitude=37.806, longitude=-122.432, radius_km=15,
                           start_date=date(2026, 10, 27), end_date=date(2026, 10, 30))
    result = await src.discover(query)
    assert [r.source_id for r in result.items] == ["evt-in"]
    assert result.run_report.unique_count == 3


async def test_keyword_category_filter_is_client_side() -> None:
    entries = [_entry("evt-1", name="Agentic AI founders mixer"), _entry("evt-2", name="Yoga")]
    src, calls = _source(lambda r, p, n: httpx.Response(200, json={"entries": entries, "has_more": False}))
    query = DiscoveryQuery(domain="events", latitude=37.8, longitude=-122.4,
                           filters={"categories": ["agentic"]})
    result = await src.discover(query)
    assert [r.source_id for r in result.items] == ["evt-1"]
    assert "category" not in calls[0] and "slug" not in calls[0]


async def test_normalize_timezone_price_venue() -> None:
    src, _ = _source(lambda r, p, n: httpx.Response(200, json={"entries": [_entry("evt-1")],
                                                                "has_more": False}))
    event = normalize((await src.discover(QUERY)).items[0], conference_id="gh-universe-2026")
    assert isinstance(event, Event)
    assert event.timezone == "America/Los_Angeles"
    assert event.start_at.isoformat() == "2026-10-27T18:00:00-07:00"  # PDT, same instant
    assert event.start_at.utcoffset().total_seconds() == -7 * 3600
    assert (event.price_min, event.price_max, event.currency, event.is_free) == (
        "20.00", "25.00", "USD", False)
    assert event.venue.coordinate_precision == "exact"
    assert event.registered_count == 42 and event.capacity is None
    assert event.conference_relation == "unknown"
    assert "luma:host:usr-1" in event.organizer_ids and "Dev Calendar" in event.organizer_names
    assert event.evidence[0].source_mode == "live" and event.evidence[0].collected_at


def test_normalize_hidden_address_and_missing_fields_stay_null() -> None:
    fx = load_fixture(FIXTURE, explicit_opt_in=True)
    rec = fx.items[0].model_copy(update={"payload": {
        "api_id": "evt-x",
        "event": {"api_id": "evt-x", "name": "Secret spot", "start_at": "2026-10-28T02:00:00Z",
                  "timezone": "America/Los_Angeles", "visibility": "public",
                  "geo_address_info": {"mode": "obfuscated", "city": "San Francisco"},
                  "geo_address_visibility": "guests-only",
                  "coordinate": {"latitude": 37.78, "longitude": -122.41}},
    }})
    event = normalize(rec)
    assert event.venue.address is None and event.venue.name is None
    assert event.venue.coordinate_precision == "approximate"
    assert event.end_at is None and event.price_min is None and event.is_free is None
    assert event.registered_count is None and event.description is None


def test_normalize_naive_or_bad_timezone_is_not_invented() -> None:
    fx = load_fixture(FIXTURE, explicit_opt_in=True)
    rec = fx.items[0].model_copy(update={"payload": {
        "api_id": "evt-y", "event": {"name": "naive", "start_at": "2026-10-28T19:00:00",
                                     "timezone": "Mars/Olympus"}}})
    event = normalize(rec)
    assert event.start_at is None and event.timezone is None


def test_fixture_requires_opt_in_and_is_labelled() -> None:
    with pytest.raises(LumaError):
        load_fixture(FIXTURE)
    fx = load_fixture(FIXTURE, explicit_opt_in=True)
    assert fx.run_report.source_mode == "fixture"
    assert fx.items and all(i.source_mode == "fixture" for i in fx.items)
    assert any("FIXTURE" in w for w in fx.run_report.warnings)
    events = [normalize(i) for i in fx.items]
    assert all(e.start_at and e.start_at.tzinfo for e in events)
    assert all(e.evidence[0].source_mode == "fixture" for e in events)
    raw = FIXTURE.read_text()
    assert "featured_guests" not in raw and "linkedin" not in raw


async def test_run_returns_envelope_without_fixture_fallback() -> None:
    src, _ = _source(lambda r, p, n: httpx.Response(500))
    env = await run(QUERY, source=src)
    assert env.status == "failed" and env.source_mode == "live" and env.items == []


DETAIL_HTML = """<html><script id="__NEXT_DATA__" type="application/json">{
 "props": {"pageProps": {"initialData": {"kind": "event", "data": {
   "api_id": "evt-1",
   "event": {"api_id": "evt-1", "name": "Detail", "start_at": "2026-10-28T01:00:00.000Z",
             "timezone": "America/Los_Angeles", "url": "detail", "visibility": "public",
             "geo_address_info": {"mode": "obfuscated", "city": "San Francisco"}},
   "hosts": [{"api_id": "usr-1", "name": "Host"}],
   "categories": [{"name": "AI"}],
   "featured_guests": [{"name": "Guest A", "avatar_url": "https://x/a.png",
                        "linkedin_handle": "/in/secret"}],
   "description_mirror": {"type": "doc", "content": [
     {"type": "paragraph", "content": [{"type": "text", "text": "Hello builders."}]}]}
 }}}}}</script></html>"""


async def test_fetch_details_parses_next_data_and_strips_guest_handles() -> None:
    src, _ = _source(lambda r, p, n: httpx.Response(200, text=DETAIL_HTML))
    rec = await src.fetch_details(SourceRef(provider="luma", source_id="detail",
                                            url="https://luma.com/detail"))
    assert rec.source_id == "evt-1" and rec.source_mode == "live"
    assert rec.payload["description_text"] == "Hello builders."
    assert rec.payload["guests_visible"] == [
        {"name": "Guest A", "avatar_url": "https://x/a.png", "bio_short": None}]
    event = normalize(rec)
    assert event.description == "Hello builders." and event.topics == ["AI"]
    assert event.venue.address is None


async def test_fetch_details_schema_drift_raises() -> None:
    src, _ = _source(lambda r, p, n: httpx.Response(200, text="<html>no data</html>"))
    with pytest.raises(LumaError, match="schema_changed"):
        await src.fetch_details(SourceRef(provider="luma", source_id="x"))
    with pytest.raises(LumaError):
        await src.fetch_details(SourceRef(provider="luma", source_id="evt-noslug"))
