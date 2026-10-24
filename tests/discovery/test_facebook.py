"""Offline tests for the Bright Data Facebook Events discovery source and normalizer."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone

import httpx
import pytest

from conferge.core.brightdata import BrightDataClient
from conferge.core.schemas import DiscoveryQuery, SourceRecord, SourceRef
from conferge.events.discovery.facebook import (
    DATASET_ID,
    PROVIDER,
    FacebookEventsError,
    FacebookEventsSource,
    normalize,
)

PAGE = "https://www.facebook.com/github"
QUERY = DiscoveryQuery(domain="events", filters={"facebook_page_urls": [PAGE]})


async def _nosleep(_: float) -> None:
    return None


def _row(event_id: str, **extra: object) -> dict:
    row = {
        "event_id": event_id,
        "name": f"Universe Party {event_id}",
        "url": f"https://www.facebook.com/events/{event_id}/",
        "start_date": "2026-10-28T18:00:00-07:00",
    }
    row.update(extra)
    return row


def _source(handler, *, api_key: str | None = "test", **kw) -> tuple[FacebookEventsSource, list]:
    calls: list[httpx.Request] = []

    def wrapped(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return handler(request, len(calls))

    client = httpx.AsyncClient(
        base_url="https://api.brightdata.com", transport=httpx.MockTransport(wrapped)
    )
    bd = BrightDataClient(api_key=api_key, client=client, retries=0)
    return FacebookEventsSource(bd, sleep=_nosleep, **kw), calls


async def test_discover_sync_success_dedupes_and_sets_params() -> None:
    rows = [_row("1"), _row("2"), _row("1")]
    src, calls = _source(lambda req, n: httpx.Response(200, json=rows))
    result = await src.discover(QUERY)
    assert [r.source_id for r in result.items] == ["1", "2"]
    report = result.run_report
    assert report.status == "ok" and report.termination == "exhausted"
    assert report.source_mode == "live"
    assert report.fetched_count == 3 and report.unique_count == 2
    rec = result.items[0]
    assert rec.provider == PROVIDER and rec.source_mode == "live"
    assert rec.collected_at.tzinfo is not None
    assert str(rec.source_url) == "https://www.facebook.com/events/1/"
    params = calls[0].url.params
    assert params["dataset_id"] == DATASET_ID
    assert params["type"] == "discover_new" and params["discover_by"] == "url"
    assert params["limit_per_input"] == "50"
    assert json.loads(calls[0].content) == {"input": [{"url": PAGE}]}


async def test_discover_location_inputs() -> None:
    src, calls = _source(lambda req, n: httpx.Response(200, json=[_row("9")]))
    query = DiscoveryQuery(
        domain="events", city="San Francisco",
        start_date=date(2026, 10, 27), end_date=date(2026, 10, 30),
    )
    result = await src.discover(query)
    assert result.run_report.status == "ok"
    assert calls[0].url.params["discover_by"] == "location"
    assert json.loads(calls[0].content) == {"input": [
        {"location": "San Francisco", "date_from": "2026-10-27", "date_to": "2026-10-30"}
    ]}


async def test_discover_202_then_polls_until_ready() -> None:
    def handler(req: httpx.Request, n: int) -> httpx.Response:
        if req.url.path == "/datasets/v3/scrape":
            return httpx.Response(202, json={"snapshot_id": "s_abc"})
        if n == 2:
            return httpx.Response(200, json={"status": "running"})
        return httpx.Response(200, json=[_row("5")])

    slept: list[float] = []

    async def sleep(seconds: float) -> None:
        slept.append(seconds)

    src, calls = _source(handler)
    src._sleep = sleep
    result = await src.discover(QUERY)
    assert result.run_report.status == "ok"
    assert [r.request_id for r in result.items] == ["s_abc"]
    assert calls[-1].url.path == "/datasets/v3/snapshot/s_abc"
    assert len(slept) == 2


async def test_discover_snapshot_still_running_is_degraded() -> None:
    def handler(req: httpx.Request, n: int) -> httpx.Response:
        if req.url.path == "/datasets/v3/scrape":
            return httpx.Response(202, json={"snapshot_id": "s_slow"})
        return httpx.Response(202, json={"status": "running"})

    src, _ = _source(handler, max_polls=3)
    result = await src.discover(QUERY)
    assert result.items == []
    assert result.run_report.status == "degraded"
    assert result.run_report.termination == "error"
    assert "snapshot still running" in result.run_report.warnings


async def test_missing_key_fails_without_items_or_http() -> None:
    src, calls = _source(lambda req, n: httpx.Response(200, json=[_row("1")]), api_key=None)
    result = await src.discover(QUERY)
    assert result.items == [] and calls == []
    assert result.run_report.status == "failed"
    assert result.run_report.termination == "error"
    assert result.run_report.source_mode == "live"
    assert "BRIGHTDATA_API_KEY" in result.errors[0]


async def test_no_client_fails() -> None:
    result = await FacebookEventsSource(None).discover(QUERY)
    assert result.run_report.status == "failed" and result.items == []


async def test_no_inputs_fails() -> None:
    src, calls = _source(lambda req, n: httpx.Response(200, json=[]))
    result = await src.discover(DiscoveryQuery(domain="events"))
    assert result.run_report.status == "failed" and calls == []


async def test_http_500_fails_with_sanitized_error() -> None:
    src, _ = _source(lambda req, n: httpx.Response(500, text="secret body"))
    result = await src.discover(QUERY)
    assert result.items == []
    assert result.run_report.status == "failed"
    assert result.run_report.termination == "error"
    assert "HTTP 500" in result.errors[0]
    assert "secret body" not in result.errors[0] and "test" not in result.errors[0]


async def test_error_rows_are_warnings_not_items() -> None:
    rows = [_row("1"), {"url": PAGE, "error": "page not found", "error_code": "dead_page"}]
    src, _ = _source(lambda req, n: httpx.Response(200, json=rows))
    result = await src.discover(QUERY)
    assert [r.source_id for r in result.items] == ["1"]
    assert result.run_report.status == "degraded"
    assert any("dead_page" in w for w in result.run_report.warnings)


async def test_zero_rows_is_degraded() -> None:
    src, _ = _source(lambda req, n: httpx.Response(200, json=[]))
    result = await src.discover(QUERY)
    assert result.run_report.status == "degraded"
    assert result.run_report.termination == "error"
    assert "zero results returned" in result.run_report.warnings


async def test_limit_reached_is_truncated() -> None:
    rows = [_row(str(i)) for i in range(2)]
    src, _ = _source(lambda req, n: httpx.Response(200, json=rows), limit_per_input=2)
    result = await src.discover(QUERY)
    assert result.run_report.status == "degraded"
    assert result.run_report.termination == "page_cap"


async def test_fetch_details_collect_by_url() -> None:
    src, calls = _source(lambda req, n: httpx.Response(200, json=[_row("77")]))
    ref = SourceRef(provider=PROVIDER, source_id="77",
                    url="https://www.facebook.com/events/77/")
    record = await src.fetch_details(ref)
    assert record.source_id == "77" and record.source_mode == "live"
    assert "discover_by" not in calls[0].url.params
    assert json.loads(calls[0].content) == {"input": [{"url": "https://www.facebook.com/events/77/"}]}


async def test_fetch_details_errors() -> None:
    src, _ = _source(lambda req, n: httpx.Response(200, json=[{"error": "x"}]))
    with pytest.raises(FacebookEventsError):
        await src.fetch_details(SourceRef(provider=PROVIDER, source_id="1"))
    with pytest.raises(FacebookEventsError):
        await src.fetch_details(
            SourceRef(provider=PROVIDER, source_id="1", url="https://www.facebook.com/events/1/")
        )
    nokey, _ = _source(lambda req, n: httpx.Response(200, json=[]), api_key=None)
    with pytest.raises(FacebookEventsError):
        await nokey.fetch_details(
            SourceRef(provider=PROVIDER, source_id="1", url="https://www.facebook.com/events/1/")
        )


# ---------------------------------------------------------------------- normalize
def _record(payload: dict) -> SourceRecord:
    return SourceRecord(
        provider=PROVIDER, source_id="123", source_mode="live",
        collected_at=datetime(2026, 10, 24, 12, 0, tzinfo=timezone.utc),
        payload=payload, request_id="s_1",
    )


def test_normalize_full_payload_with_offsets() -> None:
    event = normalize(_record({
        "event_id": "123",
        "title": "GitHub Universe Afterparty",
        "description": "Drinks after day one.",
        "start_date": "2026-10-28T18:00:00-07:00",
        "end_date": "2026-10-28T22:00:00-07:00",
        "timezone": "America/Los_Angeles",
        "location": {"name": "Fort Mason", "address": "2 Marina Blvd",
                     "city": "San Francisco", "latitude": 37.806, "longitude": -122.432},
        "hosts": [{"name": "GitHub"}, "Copilot Team"],
        "users_responded": "1,204",
        "ticket_url": "https://tickets.example.com/universe",
        "url": "https://www.facebook.com/events/123/",
    }), conference_id="github-universe-2026")
    assert event.id == "evt:facebook:123"
    assert event.conference_id == "github-universe-2026"
    assert event.event_type == "party"
    assert event.start_at == datetime(2026, 10, 29, 1, 0, tzinfo=timezone.utc)
    assert event.end_at is not None and event.end_at.utcoffset() is not None
    assert event.timezone == "America/Los_Angeles"
    assert event.venue is not None and event.venue.coordinate_precision == "exact"
    assert event.venue.city == "San Francisco"
    assert event.organizer_names == ["GitHub", "Copilot Team"]
    assert event.registered_count == 1204
    assert str(event.registration_url) == "https://tickets.example.com/universe"
    assert str(event.source_url) == "https://www.facebook.com/events/123/"
    assert event.conference_relation == "unknown"
    assert event.status == "unknown"
    ev = event.evidence[0]
    assert ev.provider == PROVIDER and ev.source_record_id == "123" and ev.raw_ref == "s_1"


def test_normalize_naive_time_is_none() -> None:
    event = normalize(_record({"name": "Meetup night", "start_time": "2026-10-28T18:00:00",
                               "timezone": "PDT"}))
    assert event.start_at is None
    assert event.timezone is None
    assert event.event_type == "meetup"


def test_normalize_cancelled_and_going() -> None:
    event = normalize(_record({"event_name": "AI workshop", "isCanceled": True, "going": 42}))
    assert event.status == "cancelled"
    assert event.registered_count == 42
    assert event.event_type == "workshop"


def test_normalize_missing_fields_are_none() -> None:
    event = normalize(_record({"name": "Hackathon", "url": "not a url",
                               "ticket_url": "javascript:alert(1)", "going": "1.2K"}))
    assert event.event_type == "other"
    assert event.description is None and event.start_at is None and event.end_at is None
    assert event.venue is None and event.organizer_names == []
    assert event.registration_url is None and event.source_url is None
    assert event.registered_count is None and event.timezone is None


def test_normalize_location_without_coords_and_string_place() -> None:
    event = normalize(_record({"name": "x", "place": {"name": "The Pier", "city": "SF"}}))
    assert event.venue is not None and event.venue.coordinate_precision == "unknown"
    assert event.venue.latitude is None
    event2 = normalize(_record({"name": "x", "location": "Fort Mason Center"}))
    assert event2.venue is not None and event2.venue.name == "Fort Mason Center"


def test_normalize_without_title_raises() -> None:
    with pytest.raises(ValueError):
        normalize(_record({"description": "no name"}))
