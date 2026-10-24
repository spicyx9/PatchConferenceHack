"""Shared offline helpers for w02 (Eventbrite + conference-party aggregators) tests."""

from __future__ import annotations

import copy
import json
import math
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx

from conferge.core.schemas import RunReport

FIXTURES_HTML = Path(__file__).resolve().parent / "fixtures_html"
COLLECTED_AT = datetime(2026, 10, 23, 12, 0, tzinfo=timezone.utc)


def read_fixture(name: str) -> str:
    return (FIXTURES_HTML / name).read_text(encoding="utf-8")


def search_page_json() -> dict[str, Any]:
    return json.loads(read_fixture("eventbrite_search_page.json"))


def real_results() -> list[dict[str, Any]]:
    return search_page_json()["events"]["results"]


def assert_report_consistent(report: RunReport, n_items: int) -> None:
    assert report.unique_count == n_items
    assert report.fetched_count >= report.unique_count
    assert report.pages >= 0
    assert report.finished_at >= report.started_at
    if report.status == "ok":
        assert report.termination in {"exhausted", "not_applicable"}


@dataclass
class FakeEventbrite:
    """In-memory Eventbrite: `per_day` events per date, paginated like the real API.

    `search_hook(body, page_no)` may return an httpx.Response to override a search
    reply (used for 429, HTML, malformed JSON...).
    """

    per_day: dict[date, int] = field(default_factory=dict)
    bootstrap_status: int = 200
    set_cookie: bool = True
    api_page_ceiling: int = 19
    search_hook: Callable[[dict[str, Any], int], httpx.Response | None] | None = None
    requests: list[httpx.Request] = field(default_factory=list)
    search_bodies: list[dict[str, Any]] = field(default_factory=list)

    def _ids(self, start: date, end: date) -> list[tuple[str, date]]:
        out: list[tuple[str, date]] = []
        day = start
        while day <= end:
            for index in range(self.per_day.get(day, 0)):
                out.append((f"{day:%Y%m%d}{index:04d}", day))
            day += timedelta(days=1)
        return out

    def _item(self, event_id: str, day: date) -> dict[str, Any]:
        item = copy.deepcopy(real_results()[0])
        item["id"] = item["eid"] = item["eventbrite_event_id"] = event_id
        item["start_date"] = item["end_date"] = day.isoformat()
        item["url"] = f"https://www.eventbrite.com/e/test-tickets-{event_id}"
        return item

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.method == "GET" and request.url.path == "/d/ca--san-francisco/events/":
            if self.bootstrap_status >= 400:
                return httpx.Response(self.bootstrap_status, text="<html>blocked</html>")
            headers = {"Set-Cookie": "csrftoken=tok123; Path=/"} if self.set_cookie else {}
            return httpx.Response(
                200, text=read_fixture("eventbrite_bootstrap.html"), headers=headers
            )
        if request.method == "POST" and request.url.path == "/api/v3/destination/search/":
            body = json.loads(request.content)
            self.search_bodies.append(body)
            search = body["event_search"]
            page_no = int(search["page"])
            if self.search_hook is not None:
                override = self.search_hook(body, page_no)
                if override is not None:
                    return override
            rng = search.get("date_range")
            if rng:
                start = date.fromisoformat(rng["from"])
                end = date.fromisoformat(rng["to"])
            else:
                start, end = min(self.per_day, default=date(2026, 1, 1)), max(
                    self.per_day, default=date(2026, 1, 1)
                )
            ids = self._ids(start, end)
            size = int(search["page_size"])
            page_count = min(math.ceil(len(ids) / size), self.api_page_ceiling)
            chunk = ids[(page_no - 1) * size: page_no * size] if page_no <= page_count else []
            data = {
                "events": {
                    "pagination": {
                        "page_size": size, "object_count": len(ids),
                        "page_number": page_no, "page_count": page_count,
                    },
                    "results": [self._item(event_id, day) for event_id, day in chunk],
                }
            }
            return httpx.Response(200, json=data)
        return httpx.Response(404, text="not mocked")

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=httpx.MockTransport(self.handler), base_url="https://www.eventbrite.com"
        )


def static_client(routes: dict[str, httpx.Response | Callable[[], httpx.Response]]) -> (
    httpx.AsyncClient
):
    """Client answering GETs by exact URL; unknown URLs get 404."""

    def handler(request: httpx.Request) -> httpx.Response:
        value = routes.get(str(request.url))
        if value is None:
            return httpx.Response(404, text="not found")
        return value() if callable(value) else value

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))
