"""Eventbrite destination search source (independent implementation).

Flow, verified live on 2026-10-23:
1. GET https://www.eventbrite.com/d/<location_slug>/events/ with a browser
   User-Agent: sets the `csrftoken` cookie and embeds `"placeId":"<id>"`
   in window.__SERVER_DATA__ (San Francisco = 85922583).
2. POST https://www.eventbrite.com/api/v3/destination/search/ with the cookie,
   header X-CSRFToken and JSON body
   {"event_search": {"date_range": {"from": D1, "to": D2}, "places": [id],
    "page": n, "page_size": 50, "q": ...}, "expand.destination_event": [...]}.
   Note: `"dates": "custom"` is rejected (ARGUMENTS_ERROR); date_range alone works.
3. Pagination exposes object_count and page_count; page_count stops at 19
   (950 rows) so wide ranges are partitioned by date (see partition.py).

Failures never fall back to fixtures here: they produce degraded/failed reports.
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from conferge.core.schemas import (
    DataEnvelope,
    DiscoveryQuery,
    DiscoveryResult,
    Event,
    RunReport,
    SourceRecord,
    SourceRef,
    Termination,
)
from conferge.events.eventbrite.normalize import normalize_records, payload_hash
from conferge.events.eventbrite.partition import DEFAULT_CAP, plan_windows

PROVIDER = "eventbrite"
BASE_URL = "https://www.eventbrite.com"
SEARCH_PATH = "/api/v3/destination/search/"
DEFAULT_LOCATION_SLUG = "ca--san-francisco"
PAGE_SIZE = 50
MAX_PAGES = 19
BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/129.0 Safari/537.36"
)
EXPANSIONS = [
    "primary_venue", "ticket_availability", "event_sales_status", "primary_organizer",
]
FIXTURE_PATH = Path(__file__).resolve().parents[3] / "fixtures" / "eventbrite-aggregators.json"
_PLACE_RE = re.compile(r'"placeId"\s*:\s*"(\d+)"')
_CITY_SLUGS = {"san francisco": "ca--san-francisco", "new york": "ny--new-york"}


class SearchFailure(RuntimeError):
    def __init__(self, termination: Termination, message: str) -> None:
        super().__init__(message)
        self.termination = termination


@dataclass
class _Run:
    records: dict[str, SourceRecord] = field(default_factory=dict)
    fetched: int = 0
    pages: int = 0
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    termination: Termination = "exhausted"
    expected: int | None = None

    def degrade(self, termination: Termination, message: str, *, error: bool = False) -> None:
        if self.termination == "exhausted":
            self.termination = termination
        (self.errors if error else self.warnings).append(message)


def _status_termination(status_code: int) -> Termination:
    if status_code in {401, 403}:
        return "blocked"
    if status_code == 429:
        return "rate_limited"
    return "error"


class EventbriteSource:
    def __init__(
        self, *, client: httpx.AsyncClient | None = None, cap: int = DEFAULT_CAP,
        request_delay: float = 0.3, max_pages: int = MAX_PAGES, timeout: float = 30.0,
    ) -> None:
        self._client = client
        self._owns_client = client is None
        self.cap = cap
        self.request_delay = request_delay
        self.max_pages = max_pages
        self.timeout = timeout
        self._csrf: str | None = None
        self._referer: str | None = None
        self._page_one: dict[tuple[Any, ...], dict[str, Any]] = {}

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=BASE_URL, timeout=self.timeout, follow_redirects=True,
                headers={"User-Agent": BROWSER_UA, "Accept-Language": "en-US,en;q=0.9"},
            )
        return self._client

    async def aclose(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    async def bootstrap(self, location_slug: str) -> str:
        """Open the browser context (cookies + CSRF); return the place id."""
        url = f"{BASE_URL}/d/{location_slug}/events/"
        try:
            response = await self._http().get(url)
        except httpx.HTTPError as exc:
            raise SearchFailure(
                "error", f"bootstrap network error: {exc.__class__.__name__}"
            ) from exc
        if response.status_code >= 400:
            raise SearchFailure(
                _status_termination(response.status_code),
                f"bootstrap HTTP {response.status_code} for {url}",
            )
        csrf = response.cookies.get("csrftoken") or self._http().cookies.get("csrftoken")
        if not csrf:
            raise SearchFailure("blocked", "failed browser context: no csrftoken cookie")
        match = _PLACE_RE.search(response.text)
        self._csrf, self._referer = csrf, url
        if not match:
            raise SearchFailure("schema_changed", "placeId not found in __SERVER_DATA__")
        return match.group(1)

    async def search_page(
        self, place_id: str, start: date | None, end: date | None, page: int,
        keywords: list[str], online_only: bool = False,
    ) -> dict[str, Any]:
        key = (start.isoformat() if start else None, end.isoformat() if end else None)
        cache_key = (place_id, *key, tuple(keywords), online_only)
        if page == 1 and cache_key in self._page_one:
            return self._page_one[cache_key]
        event_search: dict[str, Any] = {
            "places": [place_id], "page": page, "page_size": PAGE_SIZE,
            "online_events_only": online_only,
        }
        if start and end:
            event_search["date_range"] = {"from": key[0], "to": key[1]}
        if keywords:
            event_search["q"] = " ".join(keywords)
        body = {"event_search": event_search, "expand.destination_event": EXPANSIONS}
        if self.request_delay:
            await asyncio.sleep(self.request_delay)
        try:
            response = await self._http().post(
                SEARCH_PATH, json=body,
                headers={
                    "X-CSRFToken": self._csrf or "", "Referer": self._referer or BASE_URL,
                    "Content-Type": "application/json", "Accept": "application/json",
                },
            )
        except httpx.HTTPError as exc:
            raise SearchFailure(
                "error", f"search network error: {exc.__class__.__name__}"
            ) from exc
        if response.status_code >= 400:
            raise SearchFailure(
                _status_termination(response.status_code),
                f"search HTTP {response.status_code} (page {page}, {key[0]}..{key[1]})",
            )
        try:
            data = response.json()
        except json.JSONDecodeError as exc:
            raise SearchFailure(
                "schema_changed", "search returned non-JSON (HTML instead of API)"
            ) from exc
        events = data.get("events") if isinstance(data, dict) else None
        if not isinstance(events, dict) or not isinstance(events.get("results"), list) or (
            not isinstance(events.get("pagination"), dict)
        ):
            raise SearchFailure("schema_changed", "search JSON lacks events.results/pagination")
        if page == 1:
            self._page_one[cache_key] = data
        return data

    def _record(self, item: dict[str, Any], collected_at: datetime) -> SourceRecord | None:
        event_id = str(item.get("id") or item.get("eventbrite_event_id") or "")
        if not event_id:
            return None
        url = item.get("url")
        return SourceRecord(
            provider=PROVIDER, source_id=event_id, source_mode="live",
            collected_at=collected_at, payload=item,
            source_url=url if isinstance(url, str) and url.startswith("http") else None,
            content_hash=payload_hash(item),
        )

    async def _drain(
        self, run: _Run, place_id: str, start: date | None, end: date | None,
        keywords: list[str], online_only: bool, limit: int, capped: bool,
    ) -> None:
        label = f"{start}..{end}" if start else "all-dates"
        page = 1
        page_count = 1
        declared = 0
        raw_page_count = 0
        window_ids: set[str] = set()
        while page <= page_count:
            data = await self.search_page(place_id, start, end, page, keywords, online_only)
            run.pages += 1
            pagination = data["events"]["pagination"]
            results = data["events"]["results"]
            declared = int(pagination.get("object_count") or 0)
            raw_page_count = int(pagination.get("page_count") or 0)
            page_count = min(raw_page_count, self.max_pages)
            collected_at = datetime.now(timezone.utc)
            run.fetched += len(results)
            new = 0
            for item in results:
                record = self._record(item, collected_at)
                if record is None:
                    run.warnings.append(f"result_without_id:{label}:p{page}")
                    continue
                window_ids.add(record.source_id)
                if record.source_id not in run.records:
                    run.records[record.source_id] = record
                    new += 1
                if len(run.records) >= limit:
                    break
            if len(run.records) >= limit and (page < page_count or len(window_ids) < declared):
                run.degrade("page_cap", f"limit_reached:{limit} during {label}")
                return
            if not results and page < page_count:
                run.degrade("cursor_stuck", f"empty page {page}/{page_count} in {label}")
                return
            if results and new == 0 and page > 1:
                run.warnings.append(f"page_without_new_ids:{label}:p{page}")
            page += 1
        hit_ceiling = capped or raw_page_count > self.max_pages or declared > self.cap
        if hit_ceiling and len(window_ids) < declared:
            run.degrade(
                "page_cap",
                f"page_cap:{label} declared {declared}, retrieved {len(window_ids)} "
                f"(ceiling {self.max_pages * PAGE_SIZE})",
            )
        elif len(window_ids) != declared:
            # Pages drained to the end; Eventbrite's object_count is approximate.
            run.warnings.append(
                f"declared_count_mismatch:{label} declared {declared}, retrieved {len(window_ids)}"
            )

    async def discover(self, query: DiscoveryQuery) -> DiscoveryResult:
        started_at = datetime.now(timezone.utc)
        run = _Run()
        filters = query.filters
        location_slug = filters.get("location_slug") or _CITY_SLUGS.get(
            (query.city or "").lower(), DEFAULT_LOCATION_SLUG
        )
        online_only = bool(filters.get("online_events_only", False))
        # The API accepts event_search.q but ignores it (verified live 2026-10-23):
        # with keywords, drain the whole window and filter client-side.
        drain_limit = 10**6 if query.keywords else query.limit
        try:
            bootstrap_place = await self.bootstrap(location_slug)
            place_id = str(filters.get("place_id") or bootstrap_place)
            if query.start_date and query.end_date:
                start, end = query.start_date, query.end_date
            elif query.start_date or query.end_date:
                start = end = query.start_date or query.end_date
            else:
                start = end = None
            if start and end:

                async def count(lo: date, hi: date) -> int:
                    data = await self.search_page(place_id, lo, hi, 1, query.keywords, online_only)
                    return int(data["events"]["pagination"].get("object_count") or 0)

                plan = await plan_windows(count, start, end, cap=self.cap)
                run.warnings.extend(plan.warnings)
                run.expected = sum(w.declared_total or 0 for w in plan.windows) or None
                for window in plan.windows:
                    await self._drain(
                        run, place_id, window.start, window.end, query.keywords,
                        online_only, drain_limit, window.capped,
                    )
                    if run.termination == "page_cap" and len(run.records) >= drain_limit:
                        break
            else:
                run.warnings.append("no date range: single unpartitioned query")
                await self._drain(
                    run, place_id, None, None, query.keywords, online_only, drain_limit, False
                )
        except SearchFailure as failure:
            run.degrade(failure.termination, str(failure), error=True)
        finally:
            await self.aclose()

        items = list(run.records.values())
        if query.keywords:
            matched = [r for r in items if matches_keywords(r.payload, query.keywords)]
            run.warnings.append(
                f"keyword_filter_client_side:{len(matched)} of {len(items)} match "
                f"{query.keywords} (API ignores q)"
            )
            items = matched
            if len(items) > query.limit:
                items = items[: query.limit]
                run.degrade("page_cap", f"limit_reached:{query.limit} after keyword filter")
        if not items and run.termination == "exhausted":
            run.warnings.append("zero_results")
        if run.termination == "exhausted":
            status = "ok" if items else "degraded"
        else:
            status = "degraded" if items else "failed"
        report = RunReport(
            provider=PROVIDER, started_at=started_at,
            finished_at=max(datetime.now(timezone.utc), started_at),
            status=status, termination=run.termination, source_mode="live",
            fetched_count=max(run.fetched, len(items)), unique_count=len(items),
            pages=run.pages, expected_count=run.expected,
            errors=run.errors, warnings=run.warnings,
        )
        return DiscoveryResult(items=items, run_report=report, errors=list(run.errors))

    async def fetch_details(self, ref: SourceRef) -> SourceRecord:
        """Fetch the public event page and keep its schema.org JSON-LD block."""
        url = str(ref.url) if ref.url else f"{BASE_URL}/e/{ref.source_id}"
        try:
            response = await self._http().get(url)
            if response.status_code >= 400:
                raise SearchFailure(
                    _status_termination(response.status_code),
                    f"event page HTTP {response.status_code}",
                )
            blocks = extract_jsonld(response.text)
        except httpx.HTTPError as exc:
            raise SearchFailure(
                "error", f"event page network error: {exc.__class__.__name__}"
            ) from exc
        finally:
            await self.aclose()
        event_blocks = [b for b in blocks if "Event" in str(b.get("@type", ""))]
        if not event_blocks:
            raise SearchFailure("schema_changed", "no schema.org Event JSON-LD on event page")
        payload = {"jsonld": event_blocks[0], "detail_page": True}
        return SourceRecord(
            provider=PROVIDER, source_id=ref.source_id, source_mode="live",
            collected_at=datetime.now(timezone.utc), payload=payload,
            source_url=url, content_hash=payload_hash(payload),
        )


def matches_keywords(item: dict[str, Any], keywords: list[str]) -> bool:
    """Whole-word, case-insensitive match on title, summary, tags and organizer name."""
    organizer = item.get("primary_organizer") if isinstance(
        item.get("primary_organizer"), dict
    ) else {}
    tags = " ".join(
        str(tag.get("display_name", "")) for tag in item.get("tags") or [] if isinstance(tag, dict)
    )
    haystack = " ".join(
        str(part) for part in (item.get("name"), item.get("summary"), tags, organizer.get("name"))
        if part
    )
    return any(
        re.search(rf"(?<![A-Za-z0-9]){re.escape(word)}(?![A-Za-z0-9])", haystack, re.I)
        for word in keywords if word.strip()
    )


def extract_jsonld(html: str) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    for raw in re.findall(
        r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>', html, re.S | re.I
    ):
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            continue
        for item in value if isinstance(value, list) else [value]:
            if isinstance(item, dict):
                blocks.append(item)
    return blocks


async def run(
    query: DiscoveryQuery, *, source: EventbriteSource | None = None
) -> DataEnvelope[Event]:
    """Discover live Eventbrite events and normalize them (never a silent fixture)."""
    result = await (source or EventbriteSource()).discover(query)
    # Relation to the anchor conference is decided at integration, not here.
    events, errors = normalize_records(result.items, conference_id=None)
    return DataEnvelope[Event](
        items=events, source_mode="live",
        status=result.run_report.status if not errors else "degraded",
        reports=[result.run_report], errors=result.errors + errors,
    )


def load_fixture(path: str | Path = FIXTURE_PATH, *, explicit_opt_in: bool = False) -> DiscoveryResult:
    """Labelled fixture replay as a DiscoveryResult, like the luma, partiful and discovery loaders."""
    if not explicit_opt_in:
        raise RuntimeError("fixture use must be explicitly enabled and labelled")
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    records = [SourceRecord.model_validate(item) for item in data.get("eventbrite", [])]
    if any(record.source_mode != "fixture" for record in records):
        raise ValueError("fixture file contains records not labelled source_mode=fixture")
    captured = datetime.fromisoformat(data["captured_at"])
    report = RunReport(
        provider=PROVIDER, started_at=captured, finished_at=captured, status="ok",
        termination="not_applicable", source_mode="fixture", fetched_count=len(records),
        unique_count=len({r.source_id for r in records}), pages=0,
        warnings=[f"FIXTURE: {Path(path).name}; captured {data['captured_at']}; not live"],
    )
    return DiscoveryResult(items=records, run_report=report)


def load_fixture_records(*, explicit_opt_in: bool = False) -> list[SourceRecord]:
    """Backward-compatible alias: the records of `load_fixture`."""
    return load_fixture(FIXTURE_PATH, explicit_opt_in=explicit_opt_in).items
