"""EventbriteSource.discover against an in-memory MockTransport (no network)."""

from __future__ import annotations

from datetime import date

import httpx
import pytest
from w02_helpers import FakeEventbrite, assert_report_consistent

from conferge.core.schemas import DiscoveryQuery
from conferge.events.eventbrite import source as eb_source
from conferge.events.eventbrite.source import EventbriteSource

D27, D28, D29, D30 = (date(2026, 10, d) for d in (27, 28, 29, 30))


def _query(start: date | None = D27, end: date | None = D30, limit: int = 1000, **kw):
    return DiscoveryQuery(
        domain="events", city="San Francisco", start_date=start, end_date=end, limit=limit, **kw
    )


def _source(fake: FakeEventbrite, **kw) -> EventbriteSource:
    return EventbriteSource(client=fake.client(), request_delay=0, **kw)


async def test_small_range_exhausted_ok_and_request_shape() -> None:
    fake = FakeEventbrite(per_day={D28: 30, D29: 12})
    result = await _source(fake).discover(_query())
    report = result.run_report
    assert report.status == "ok"
    assert report.termination == "exhausted"
    assert report.source_mode == "live"
    assert len(result.items) == 42
    assert_report_consistent(report, 42)
    assert report.fetched_count == 42
    assert report.expected_count == 42
    assert report.pages == 1
    assert all(item.source_mode == "live" for item in result.items)
    assert all(item.collected_at.tzinfo is not None for item in result.items)
    assert all(str(item.source_url).startswith("https://www.eventbrite.com/e/") for item in result.items)

    # bootstrap first, then the search POST with CSRF header and cookie
    assert fake.requests[0].method == "GET"
    assert fake.requests[0].url.path == "/d/ca--san-francisco/events/"
    posts = [r for r in fake.requests if r.method == "POST"]
    assert posts
    for request in posts:
        assert request.headers["X-CSRFToken"] == "tok123"
        assert "csrftoken=tok123" in request.headers.get("cookie", "")
        assert request.headers["Content-Type"].startswith("application/json")
    body = fake.search_bodies[0]
    search = body["event_search"]
    assert search["date_range"] == {"from": "2026-10-27", "to": "2026-10-30"}
    assert search["page"] == 1
    assert search["page_size"] == 50
    assert search["places"] == ["85922583"]
    assert "dates" not in search  # "dates": "custom" is rejected by Eventbrite
    assert "primary_venue" in body["expand.destination_event"]


async def test_keywords_and_place_override_in_body() -> None:
    fake = FakeEventbrite(per_day={D28: 2})
    result = await _source(fake).discover(
        _query(D28, D28, keywords=["trivia", "agents"], filters={"place_id": "999"})
    )
    assert result.run_report.status == "ok"
    assert len(result.items) == 2  # template title "TRIVIA with ..." matches whole-word
    search = fake.search_bodies[0]["event_search"]
    assert search["q"] == "trivia agents"
    assert search["places"] == ["999"]
    assert any(w.startswith("keyword_filter_client_side:2 of 2") for w in result.run_report.warnings)


async def test_keywords_filtered_client_side_no_match() -> None:
    fake = FakeEventbrite(per_day={D28: 5})
    result = await _source(fake).discover(_query(D28, D28, keywords=["agents"]))
    report = result.run_report
    assert result.items == []
    assert report.status == "degraded"
    assert report.termination == "exhausted"
    assert "zero_results" in report.warnings
    assert report.fetched_count == 5 and report.unique_count == 0


async def test_keywords_drain_whole_window_then_limit() -> None:
    fake = FakeEventbrite(per_day={D28: 120})
    result = await _source(fake).discover(_query(D28, D28, limit=30, keywords=["trivia"]))
    report = result.run_report
    assert report.pages == 3  # full drain despite the small limit
    assert len(result.items) == 30
    assert report.termination == "page_cap"
    assert report.status == "degraded"
    assert any("after keyword filter" in w for w in report.warnings)
    assert_report_consistent(report, 30)


async def test_pagination_multiple_pages_in_one_window() -> None:
    fake = FakeEventbrite(per_day={D28: 120})
    result = await _source(fake).discover(_query(D28, D28))
    report = result.run_report
    assert report.status == "ok" and report.termination == "exhausted"
    assert len(result.items) == 120
    assert report.pages == 3
    pages = [b["event_search"]["page"] for b in fake.search_bodies]
    # page 1 is cached from the count probe, so it is only requested once
    assert pages == [1, 2, 3]
    assert_report_consistent(report, 120)


async def test_declared_total_above_cap_partitions_and_stays_ok() -> None:
    fake = FakeEventbrite(per_day={D27: 40, D28: 40, D29: 40, D30: 40})
    result = await _source(fake, cap=60).discover(_query())
    report = result.run_report
    assert report.status == "ok", report
    assert report.termination == "exhausted"
    assert len(result.items) == 160
    assert len({r.source_id for r in result.items}) == 160
    assert_report_consistent(report, 160)
    ranges = {
        (b["event_search"]["date_range"]["from"], b["event_search"]["date_range"]["to"])
        for b in fake.search_bodies
    }
    assert ("2026-10-27", "2026-10-30") in ranges  # initial probe
    for day in ("2026-10-27", "2026-10-28", "2026-10-29", "2026-10-30"):
        assert (day, day) in ranges
    assert report.expected_count == 160
    assert report.pages == 4  # one drained page per single-day window


async def test_single_day_above_cap_page_cap_degraded_keeps_items() -> None:
    fake = FakeEventbrite(per_day={D28: 200})
    result = await _source(fake, cap=60, max_pages=2).discover(_query(D28, D28))
    report = result.run_report
    assert report.termination == "page_cap"
    assert report.status == "degraded"
    assert len(result.items) == 100  # partial results stay usable
    assert report.pages == 2
    assert report.fetched_count == 100
    assert report.expected_count == 200
    assert any(w.startswith("page_cap:") for w in report.warnings)
    assert_report_consistent(report, 100)


async def test_zero_results_degraded_exhausted() -> None:
    fake = FakeEventbrite(per_day={})
    result = await _source(fake).discover(_query())
    report = result.run_report
    assert result.items == []
    assert report.status == "degraded"
    assert report.termination == "exhausted"
    assert "zero_results" in report.warnings
    assert report.unique_count == 0 and report.fetched_count == 0
    assert report.expected_count is None


async def test_bootstrap_403_failed_blocked() -> None:
    fake = FakeEventbrite(per_day={D28: 5}, bootstrap_status=403)
    result = await _source(fake).discover(_query())
    report = result.run_report
    assert report.status == "failed"
    assert report.termination == "blocked"
    assert result.items == []
    assert result.errors and "403" in result.errors[0]
    assert not any(r.method == "POST" for r in fake.requests)
    assert report.pages == 0


async def test_bootstrap_without_csrf_cookie_blocked() -> None:
    fake = FakeEventbrite(per_day={D28: 5}, set_cookie=False)
    result = await _source(fake).discover(_query())
    report = result.run_report
    assert report.status == "failed"
    assert report.termination == "blocked"
    assert any("csrftoken" in e for e in result.errors)
    assert not any(r.method == "POST" for r in fake.requests)


async def test_bootstrap_without_place_id_schema_changed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, text="<html>no server data</html>", headers={"Set-Cookie": "csrftoken=x; Path=/"}
        )

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://www.eventbrite.com"
    )
    result = await EventbriteSource(client=client, request_delay=0).discover(_query())
    assert result.run_report.termination == "schema_changed"
    assert result.run_report.status == "failed"


async def test_bootstrap_network_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://www.eventbrite.com"
    )
    result = await EventbriteSource(client=client, request_delay=0).discover(_query())
    assert result.run_report.status == "failed"
    assert result.run_report.termination == "error"


async def test_search_429_midway_rate_limited_keeps_items() -> None:
    def hook(body, page_no):
        return httpx.Response(429, text="slow down") if page_no == 3 else None

    fake = FakeEventbrite(per_day={D28: 140}, search_hook=hook)
    result = await _source(fake).discover(_query(D28, D28))
    report = result.run_report
    assert report.termination == "rate_limited"
    assert report.status == "degraded"
    assert len(result.items) == 100
    assert report.pages == 2
    assert any("429" in e for e in report.errors)
    assert_report_consistent(report, 100)


async def test_search_403_first_page_failed_blocked() -> None:
    fake = FakeEventbrite(
        per_day={D28: 10}, search_hook=lambda body, page: httpx.Response(403, text="no")
    )
    result = await _source(fake).discover(_query(D28, D28))
    assert result.run_report.status == "failed"
    assert result.run_report.termination == "blocked"


async def test_search_returns_html_schema_changed() -> None:
    fake = FakeEventbrite(
        per_day={D28: 10},
        search_hook=lambda body, page: httpx.Response(
            200, text="<html><body>Please enable JS</body></html>",
            headers={"Content-Type": "text/html"},
        ),
    )
    result = await _source(fake).discover(_query(D28, D28))
    report = result.run_report
    assert report.termination == "schema_changed"
    assert report.status == "failed"
    assert any("non-JSON" in e for e in report.errors)


@pytest.mark.parametrize(
    "payload",
    [
        {"something": "else"},
        {"events": {"results": []}},
        {"events": {"pagination": {"object_count": 1}}},
        {"events": []},
        [],
    ],
)
async def test_search_json_without_events_schema_changed(payload) -> None:
    fake = FakeEventbrite(
        per_day={D28: 10}, search_hook=lambda body, page: httpx.Response(200, json=payload)
    )
    result = await _source(fake).discover(_query(D28, D28))
    assert result.run_report.termination == "schema_changed"
    assert result.run_report.status == "failed"


async def test_schema_change_on_later_page_keeps_items_degraded() -> None:
    def hook(body, page_no):
        return httpx.Response(200, json={"error": "changed"}) if page_no == 2 else None

    fake = FakeEventbrite(per_day={D28: 80}, search_hook=hook)
    result = await _source(fake).discover(_query(D28, D28))
    assert result.run_report.termination == "schema_changed"
    assert result.run_report.status == "degraded"
    assert len(result.items) == 50


async def test_limit_reached_page_cap_degraded() -> None:
    fake = FakeEventbrite(per_day={D28: 120})
    result = await _source(fake).discover(_query(D28, D28, limit=30))
    report = result.run_report
    assert report.termination == "page_cap"
    assert report.status == "degraded"
    assert len(result.items) == 30
    assert any(w.startswith("limit_reached:30") for w in report.warnings)
    assert report.pages == 1
    assert_report_consistent(report, 30)


async def test_limit_reached_across_windows_stops_early() -> None:
    fake = FakeEventbrite(per_day={D27: 40, D28: 40, D29: 40, D30: 40})
    result = await _source(fake, cap=60).discover(_query(limit=50))
    report = result.run_report
    assert report.termination == "page_cap"
    assert report.status == "degraded"
    assert len(result.items) == 50
    drained_last_day = [
        b for b in fake.search_bodies
        if b["event_search"]["date_range"] == {"from": "2026-10-30", "to": "2026-10-30"}
        and b["event_search"]["page"] > 1
    ]
    assert drained_last_day == []


async def test_single_date_query_uses_one_day_range() -> None:
    fake = FakeEventbrite(per_day={D28: 3})
    result = await _source(fake).discover(_query(D28, None))
    assert result.run_report.status == "ok"
    assert fake.search_bodies[0]["event_search"]["date_range"] == {
        "from": "2026-10-28", "to": "2026-10-28",
    }


async def test_no_date_range_single_unpartitioned_query() -> None:
    fake = FakeEventbrite(per_day={D28: 3})
    result = await _source(fake).discover(_query(None, None))
    assert "date_range" not in fake.search_bodies[0]["event_search"]
    assert any("no date range" in w for w in result.run_report.warnings)
    assert len(result.items) == 3


async def test_duplicate_ids_across_pages_counted_once() -> None:
    # page 2 repeats page 1 ids: fetched counts both, unique counts once
    fake = FakeEventbrite(per_day={D28: 60})
    original = fake._item

    def same_ids(event_id: str, day: date):
        return original(f"dup{int(event_id[-4:]) % 50}", day)

    fake._item = same_ids  # type: ignore[method-assign]
    result = await _source(fake).discover(_query(D28, D28))
    report = result.run_report
    assert report.fetched_count == 60
    assert report.unique_count == 50 == len(result.items)
    assert any(w.startswith("page_without_new_ids") for w in report.warnings)


async def test_run_envelope_normalizes_live_items() -> None:
    fake = FakeEventbrite(per_day={D28: 3})
    envelope = await eb_source.run(_query(D28, D28), source=_source(fake))
    assert envelope.status == "ok"
    assert envelope.source_mode == "live"
    assert len(envelope.items) == 3
    assert all(e.conference_relation == "unknown" for e in envelope.items)
    assert all(e.evidence and e.evidence[0].source_mode == "live" for e in envelope.items)


async def test_new_york_city_slug() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        return httpx.Response(403)

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://www.eventbrite.com"
    )
    query = DiscoveryQuery(domain="events", city="New York", start_date=D28, end_date=D28)
    await EventbriteSource(client=client, request_delay=0).discover(query)
    assert seen == ["/d/ny--new-york/events/"]
