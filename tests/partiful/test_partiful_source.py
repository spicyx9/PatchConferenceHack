"""Offline tests for PartifulSource: buildId rotation, union/dedup, completeness, drift."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import httpx
import pytest

from conferge.core.schemas import DiscoveryQuery, SourceRef
from conferge.events.partiful import PartifulError, PartifulSource, load_fixture, normalize, run

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "partiful.json"
QUERY = DiscoveryQuery(domain="events", city="San Francisco", limit=1000)


async def _nosleep(_: float) -> None:
    return None


def _html(build_id: str) -> str:
    return ('<html><script id="__NEXT_DATA__" type="application/json">'
            + json.dumps({"buildId": build_id, "props": {"pageProps": {}}}) + "</script></html>")


def _item(eid: str, start: str = "2026-10-29T02:00:00.000Z") -> dict:
    return {"id": f"event-{eid}", "type": "event", "event": {
        "id": eid, "title": f"Party {eid}", "startDate": start,
        "endDate": "2026-10-29T05:00:00.000Z", "timezone": "America/Los_Angeles",
        "status": "PUBLISHED", "isPublic": True, "showGuestCount": True, "goingGuestCount": 12,
        "ownerIds": ["owner1"], "hostName": "Host Name",
        "locationInfo": {"type": "structured", "mapsInfo": {
            "addressLines": ["2 Marina Blvd", "San Francisco, CA 94123"],
            "approximateLocation": "San Francisco, CA"}},
    }}


def _props(counts: dict | None = None) -> dict:
    props = {
        "trendingSection": {"items": [_item("a"), _item("b")]},
        "sections": [{"title": "S1", "items": [_item("b"), _item("c")]},
                     {"title": "S2", "items": [{"type": "curator"}]}],
        "feedItems": [_item("c"), _item("d", start="2026-11-20T02:00:00.000Z")],
    }
    if counts is not None:
        props["regionEventCounts"] = counts
    return {"pageProps": props}


def _source(routes) -> tuple[PartifulSource, list[str]]:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return routes(request.url.path, len(calls))

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return PartifulSource(client=client, sleep=_nosleep), calls


def _simple(props: dict, build: str = "B1"):
    def routes(path: str, n: int) -> httpx.Response:
        if path == "/explore/sf":
            return httpx.Response(200, text=_html(build))
        if path == f"/_next/data/{build}/explore/sf.json":
            return httpx.Response(200, json=props)
        return httpx.Response(404)
    return routes


async def test_union_dedup_and_degraded_when_total_unknown() -> None:
    src, calls = _source(_simple(_props()))
    result = await src.discover(QUERY)
    rep = result.run_report
    assert sorted(r.source_id for r in result.items) == ["a", "b", "c", "d"]
    assert rep.fetched_count == 6 and rep.unique_count == 4
    assert (rep.status, rep.termination, rep.expected_count) == ("degraded", "page_cap", None)
    assert any("regionEventCounts missing" in w for w in rep.warnings)
    assert calls == ["/explore/sf", "/_next/data/B1/explore/sf.json"]
    rec = result.items[0]
    assert rec.source_mode == "live" and rec.collected_at.tzinfo
    assert str(rec.source_url) == "https://partiful.com/e/a"
    assert rec.payload["event"]["title"] == "Party a"


async def test_declared_total_matched_is_ok_else_degraded() -> None:
    src, _ = _source(_simple(_props({"SF": 4})))
    rep = (await src.discover(QUERY)).run_report
    assert (rep.status, rep.termination, rep.expected_count) == ("ok", "exhausted", 4)
    src, _ = _source(_simple(_props({"SF": 42})))
    rep = (await src.discover(QUERY)).run_report
    assert (rep.status, rep.termination, rep.expected_count) == ("degraded", "page_cap", 42)


async def test_build_id_404_rescraped_once() -> None:
    def routes(path: str, n: int) -> httpx.Response:
        if path == "/explore/sf":
            return httpx.Response(200, text=_html("OLD" if n == 1 else "NEW"))
        if path == "/_next/data/NEW/explore/sf.json":
            return httpx.Response(200, json=_props())
        return httpx.Response(404)
    src, calls = _source(routes)
    result = await src.discover(QUERY)
    assert len(result.items) == 4
    assert any("buildIdRotated" in w for w in result.run_report.warnings)
    assert calls == ["/explore/sf", "/_next/data/OLD/explore/sf.json", "/explore/sf",
                     "/_next/data/NEW/explore/sf.json"]


async def test_build_id_404_twice_fails() -> None:
    def routes(path: str, n: int) -> httpx.Response:
        if path == "/explore/sf":
            return httpx.Response(200, text=_html("OLD"))
        return httpx.Response(404)
    src, calls = _source(routes)
    result = await src.discover(QUERY)
    assert result.run_report.status == "failed" and result.items == []
    assert len(calls) == 4


async def test_missing_build_id_is_schema_changed() -> None:
    src, _ = _source(lambda path, n: httpx.Response(200, text="<html>no next data</html>"))
    rep = (await src.discover(QUERY)).run_report
    assert (rep.status, rep.termination) == ("failed", "schema_changed")


async def test_changed_json_schema() -> None:
    src, _ = _source(_simple({"props": {}}))
    rep = (await src.discover(QUERY)).run_report
    assert (rep.status, rep.termination) == ("failed", "schema_changed")
    src, _ = _source(_simple({"pageProps": {"newLayout": []}}))
    result = await src.discover(QUERY)
    assert result.run_report.status == "degraded" and result.items == []
    assert any("trendingSection" in w for w in result.run_report.warnings)


async def test_blocked_403_and_rate_limited() -> None:
    src, _ = _source(lambda path, n: httpx.Response(403))
    rep = (await src.discover(QUERY)).run_report
    assert (rep.status, rep.termination) == ("failed", "blocked")
    src, _ = _source(lambda path, n: httpx.Response(429))
    rep = (await src.discover(QUERY)).run_report
    assert (rep.status, rep.termination) == ("failed", "rate_limited")


async def test_date_window_filter() -> None:
    src, _ = _source(_simple(_props()))
    query = DiscoveryQuery(domain="events", start_date=date(2026, 10, 27),
                           end_date=date(2026, 10, 30), radius_km=5)
    result = await src.discover(query)
    assert sorted(r.source_id for r in result.items) == ["a", "b", "c"]
    assert any("radius filter not applied" in w for w in result.run_report.warnings)


async def test_normalize_timezone_and_venue() -> None:
    src, _ = _source(_simple(_props()))
    rec = (await src.discover(QUERY)).items[0]
    event = normalize(rec)
    assert event.id == "partiful:a" and event.timezone == "America/Los_Angeles"
    assert event.start_at.isoformat() == "2026-10-28T19:00:00-07:00"
    assert event.venue.address == "2 Marina Blvd, San Francisco, CA 94123"
    assert event.venue.city == "San Francisco" and event.venue.latitude is None
    assert event.registered_count == 12 and event.status == "scheduled"
    assert event.price_min is None and event.is_free is None  # no offers in feed
    assert event.organizer_names == ["Host Name"] and event.conference_relation == "unknown"


DETAIL = {"props": {"pageProps": {
    "event": {"id": "a", "title": "Party a", "startDate": "2026-10-29T02:00:00.000Z",
              "timezone": "America/Los_Angeles", "status": "PUBLISHED", "isPublic": True,
              "visibility": "public", "guestStatusCounts": {"GOING": 3}},
    "hosts": [{"id": "h1", "name": "Host", "photo": {"url": "x"}}],
    "guest": None,
    "offersJsonLd": [{"price": 25, "priceCurrency": "USD"}, {"price": 0, "priceCurrency": "USD"}],
    "structuredEventLocationJsonLd": {"address": {"addressLocality": "San Francisco"}},
    "passwordRequired": False}}}


def _detail_html(data: dict) -> str:
    return ('<script id="__NEXT_DATA__" type="application/json">' + json.dumps(data)
            + "</script>")


async def test_fetch_details_public_page_prices() -> None:
    src, _ = _source(lambda path, n: httpx.Response(200, text=_detail_html(DETAIL)))
    rec = await src.fetch_details(SourceRef(provider="partiful", source_id="a"))
    assert rec.payload["hosts"] == [{"id": "h1", "name": "Host"}]
    assert "guestStatusCounts" not in rec.payload["event"]
    event = normalize(rec)
    assert (event.price_min, event.price_max, event.currency, event.is_free) == (
        "0.00", "25.00", "USD", False)


async def test_fetch_details_refuses_private_or_password() -> None:
    private = json.loads(json.dumps(DETAIL))
    private["props"]["pageProps"]["passwordRequired"] = True
    src, _ = _source(lambda path, n: httpx.Response(200, text=_detail_html(private)))
    with pytest.raises(PartifulError, match="password"):
        await src.fetch_details(SourceRef(provider="partiful", source_id="a"))
    private["props"]["pageProps"]["passwordRequired"] = False
    private["props"]["pageProps"]["event"]["visibility"] = "private"
    src, _ = _source(lambda path, n: httpx.Response(200, text=_detail_html(private)))
    with pytest.raises(PartifulError, match="not public"):
        await src.fetch_details(SourceRef(provider="partiful", source_id="a"))


async def test_fetch_guests_not_implemented() -> None:
    with pytest.raises(NotImplementedError):
        await PartifulSource().fetch_guests(SourceRef(provider="partiful", source_id="a"))


def test_fixture_requires_opt_in_and_is_labelled() -> None:
    with pytest.raises(PartifulError):
        load_fixture(FIXTURE)
    fx = load_fixture(FIXTURE, explicit_opt_in=True)
    assert fx.run_report.source_mode == "fixture" and fx.run_report.status == "degraded"
    assert fx.items and all(i.source_mode == "fixture" for i in fx.items)
    events = [normalize(i) for i in fx.items]
    assert all(e.start_at and e.start_at.tzinfo for e in events)
    assert "ownerIds" not in FIXTURE.read_text()


async def test_run_failed_has_no_fixture_fallback() -> None:
    src, _ = _source(lambda path, n: httpx.Response(500))
    env = await run(QUERY, source=src)
    assert env.status == "failed" and env.items == [] and env.source_mode == "live"
