"""Partiful public Explore adapter.

1. GET https://partiful.com/explore/<region> and read `buildId` from `__NEXT_DATA__`;
2. GET https://partiful.com/_next/data/<buildId>/explore/<region>.json;
3. a 404 means the buildId rotated: re-scrape it once (drift signal `buildIdRotated`);
4. union `trendingSection.items`, `sections[].items`, `feedItems`, dedup by `event.id`.

Explore is a curated single page, not a paginated catalogue: completeness is unknown
unless `pageProps.regionEventCounts[<REGION>]` is present and matched, so the run is
`degraded` by default. Guest lists need a signed-in session and are out of scope.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any

import httpx

from conferge.core.brightdata import BrightDataClient, BrightDataError
from conferge.core.schemas import (
    DiscoveryQuery,
    DiscoveryResult,
    RunReport,
    SourceRecord,
    SourceRef,
    Termination,
)
from conferge.events.luma._util import content_hash, extract_next_data, local_date, parse_instant, zone

PROVIDER = "partiful"
BASE = "https://partiful.com"
HEADERS = {
    "Accept": "text/html,application/json",
    "User-Agent": "Mozilla/5.0 (compatible; Conferge/0.1; +https://github.com/spicyx9/HTest)",
}
_RETRYABLE = {429, 500, 502, 503, 504}


class PartifulError(RuntimeError):
    """Visible Partiful collection failure."""


class _HttpStatus(Exception):
    def __init__(self, status: int) -> None:
        super().__init__(f"HTTP {status}")
        self.status = status


class PartifulSource:
    """`conferge.core.contracts.Source` implementation for Partiful Explore."""

    provider = PROVIDER

    def __init__(
        self,
        *,
        client: httpx.AsyncClient | None = None,
        brightdata: BrightDataClient | None = None,
        region: str = "sf",
        retries: int = 1,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._client = client
        self._brightdata = brightdata
        self.region = region
        self.retries = retries
        self._sleep = sleep

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=30.0, headers=HEADERS)
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()

    async def _get_text(self, url: str, warnings: list[str]) -> str:
        status = 0
        for attempt in range(self.retries + 1):
            response = await self._http().get(url, headers=HEADERS)
            status = response.status_code
            if status < 400:
                return response.text
            if status in _RETRYABLE and attempt < self.retries:
                await self._sleep(min(2**attempt, 4))
                continue
            break
        bd = self._brightdata
        if status in {403, 429} and bd and bd.unlocker_zone and getattr(bd, "_api_key", None):
            warnings.append(f"direct HTTP {status}; retried via Bright Data Web Unlocker")
            try:
                return await bd.unlock(url)
            except BrightDataError as exc:
                warnings.append(f"Web Unlocker failed: {exc}")
        raise _HttpStatus(status)

    async def _build_id(self, region: str, warnings: list[str]) -> str:
        html = await self._get_text(f"{BASE}/explore/{region}", warnings)
        data = extract_next_data(html)
        build_id = (data or {}).get("buildId")
        if not isinstance(build_id, str) or not build_id:
            raise PartifulError("buildId not found in explore page __NEXT_DATA__ (schema_changed)")
        return build_id

    async def discover(self, query: DiscoveryQuery) -> DiscoveryResult:
        started = datetime.now(timezone.utc)
        region = str(query.filters.get("region") or self.region).lower()
        warnings: list[str] = []
        errors: list[str] = []
        termination: Termination = "error"
        pages = fetched = 0
        expected: int | None = None
        by_id: dict[str, SourceRecord] = {}
        page_props: dict[str, Any] | None = None

        try:
            build_id = await self._build_id(region, warnings)
            for attempt in range(2):
                try:
                    body = await self._get_text(
                        f"{BASE}/_next/data/{build_id}/explore/{region}.json", warnings
                    )
                    break
                except _HttpStatus as exc:
                    if exc.status != 404 or attempt == 1:
                        raise
                    warnings.append("driftSignals.buildIdRotated: 404 on _next/data; re-scraped buildId")
                    build_id = await self._build_id(region, warnings)
            collected_at = datetime.now(timezone.utc)
            data = json.loads(body)
            page_props = data.get("pageProps") if isinstance(data, dict) else None
            if not isinstance(page_props, dict):
                raise PartifulError("pageProps missing in explore JSON (schema_changed)")
        except _HttpStatus as exc:
            termination = "blocked" if exc.status == 403 else (
                "rate_limited" if exc.status == 429 else "error")
            errors.append(f"Partiful explore: {exc}")
        except json.JSONDecodeError:
            termination = "schema_changed"
            errors.append("Partiful explore data is not JSON")
        except PartifulError as exc:
            termination = "schema_changed"
            errors.append(str(exc))
        except httpx.HTTPError as exc:
            termination = "error"
            errors.append(f"Partiful explore: {type(exc).__name__}: {exc}")

        if page_props is not None:
            pages = 1
            groups = self._item_groups(page_props, warnings)
            for group, items in groups:
                for item in items:
                    rec = self._record(item, group, collected_at, warnings)
                    if rec is None:
                        continue
                    fetched += 1
                    if rec.source_id not in by_id:
                        by_id[rec.source_id] = rec
            counts = page_props.get("regionEventCounts")
            if isinstance(counts, dict) and isinstance(counts.get(region.upper()), int):
                expected = counts[region.upper()]
            else:
                warnings.append("pageProps.regionEventCounts missing: declared total unknown "
                                "(schema drift signal)")
            if expected is not None and len(by_id) >= expected:
                termination = "exhausted"
            else:
                termination = "page_cap"
                warnings.append(
                    "Explore is a curated single page; regional completeness not claimed "
                    f"({len(by_id)} unique vs declared {expected})"
                )

        unique = list(by_id.values())
        items = self._filter(unique, query, warnings)
        if termination == "exhausted":
            status = "ok"
        elif pages:
            status = "degraded"
        else:
            status = "failed"
        report = RunReport(
            provider=PROVIDER, started_at=started, finished_at=datetime.now(timezone.utc),
            status=status, termination=termination, source_mode="live",
            fetched_count=fetched, unique_count=len(unique), pages=pages,
            expected_count=expected, errors=errors, warnings=warnings,
        )
        return DiscoveryResult(items=items, run_report=report, errors=list(errors))

    @staticmethod
    def _item_groups(
        page_props: dict[str, Any], warnings: list[str]
    ) -> list[tuple[str, list[Any]]]:
        groups: list[tuple[str, list[Any]]] = []
        trending = page_props.get("trendingSection")
        if isinstance(trending, dict) and isinstance(trending.get("items"), list):
            groups.append(("trending", trending["items"]))
        else:
            warnings.append("trendingSection.items missing (schema drift)")
        sections = page_props.get("sections")
        if isinstance(sections, list):
            for section in sections:
                if isinstance(section, dict) and isinstance(section.get("items"), list):
                    groups.append((f"section:{section.get('title') or section.get('id')}",
                                   section["items"]))
        else:
            warnings.append("sections missing (schema drift)")
        feed = page_props.get("feedItems")
        if isinstance(feed, list):
            groups.append(("feed", feed))
        else:
            warnings.append("feedItems missing (schema drift)")
        return groups

    @staticmethod
    def _record(
        item: Any, group: str, collected_at: datetime, warnings: list[str]
    ) -> SourceRecord | None:
        if not isinstance(item, dict):
            return None
        if item.get("type") not in {None, "event"}:
            return None  # non-event tiles (promos, curators)
        event = item.get("event")
        if not isinstance(event, dict) or not isinstance(event.get("id"), str):
            warnings.append(f"{group}: item without event.id skipped (schema drift)")
            return None
        payload = {"event": event, "tags": item.get("tags"), "explore_group": group}
        return SourceRecord(
            provider=PROVIDER,
            source_id=event["id"],
            source_mode="live",
            collected_at=collected_at,
            payload=payload,
            source_url=f"{BASE}/e/{event['id']}",
            request_id="explore",
            content_hash=content_hash(payload),
        )

    @staticmethod
    def _filter(
        records: list[SourceRecord], query: DiscoveryQuery, warnings: list[str]
    ) -> list[SourceRecord]:
        keywords = [k.lower() for k in query.keywords]
        kept = []
        for rec in records:
            event = rec.payload["event"]
            tz = zone(event.get("timezone"))
            start = local_date(parse_instant(event.get("startDate")), tz)
            end = local_date(parse_instant(event.get("endDate")), tz) or start
            if query.start_date or query.end_date:
                if start is None:
                    continue
                if query.end_date and start > query.end_date:
                    continue
                if query.start_date and (end or start) < query.start_date:
                    continue
            if keywords:
                hay = f"{event.get('title') or ''} {event.get('description') or ''}".lower()
                if not any(k in hay for k in keywords):
                    continue
            kept.append(rec)
        if query.radius_km is not None:
            warnings.append("Partiful feed has no coordinates; radius filter not applied")
        if len(kept) != len(records):
            warnings.append(f"client-side filters kept {len(kept)} of {len(records)} unique events")
        if len(kept) > query.limit:
            warnings.append(f"result truncated to query.limit={query.limit} of {len(kept)}")
            kept = kept[: query.limit]
        return kept

    async def fetch_details(self, ref: SourceRef) -> SourceRecord:
        """Public event page only; password-protected or private events are refused."""
        url = str(ref.url) if ref.url else f"{BASE}/e/{ref.source_id}"
        warnings: list[str] = []
        try:
            html = await self._get_text(url, warnings)
        except _HttpStatus as exc:
            raise PartifulError(f"Partiful event page {exc}") from exc
        collected_at = datetime.now(timezone.utc)
        props = ((extract_next_data(html) or {}).get("props") or {}).get("pageProps") or {}
        if props.get("passwordRequired"):
            raise PartifulError("Partiful event is password protected; not fetched")
        event = props.get("event")
        if not isinstance(event, dict) or not event.get("id"):
            raise PartifulError("Partiful event page: pageProps.event missing (schema_changed)")
        if event.get("isPublic") is False or event.get("visibility") not in {None, "public"}:
            raise PartifulError("Partiful event is not public; not fetched")
        keep = (
            "id", "title", "description", "startDate", "endDate", "timezone", "locationInfo",
            "status", "isPublic", "visibility", "goingGuestCount", "interestedGuestCount",
            "showGuestCount", "isCapped", "atCapacity", "ownerIds", "publishedAt", "image",
        )
        slim_event = {k: event.get(k) for k in keep if k in event}
        hosts = [
            {"id": h.get("id"), "name": h.get("name")}
            for h in props.get("hosts") or [] if isinstance(h, dict) and h.get("name")
        ]
        payload = {
            "event": slim_event,
            "hosts": hosts,
            "offers": props.get("offersJsonLd"),
            "place": props.get("structuredEventLocationJsonLd"),
            "detail_warnings": warnings,
        }
        return SourceRecord(
            provider=PROVIDER, source_id=str(event["id"]), source_mode="live",
            collected_at=collected_at, payload=payload, source_url=url,
            request_id="event-page", content_hash=content_hash(payload),
        )

    async def fetch_guests(self, ref: SourceRef) -> list[dict[str, Any]]:
        # TODO(phase 2): signed-in Bright Data Browser API session, only for events the
        # account is registered to. Never scrape guest lists anonymously.
        raise NotImplementedError("Partiful guest lists require an authenticated session")
