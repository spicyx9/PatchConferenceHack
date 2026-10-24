"""Luma public geographic discovery (`api2.luma.com/discover/get-paginated-events`).

Rules (docs/knowledge/05-events.md):
- paginate with `pagination_cursor` only (`cursor` is silently ignored -> infinite loop),
  never pass `slug`;
- drain until `has_more=false` -- that is the only proof of exhaustion (no total exists);
- a repeated cursor, or `has_more=true` with no new id, is `cursor_stuck` (degraded);
- at most `max_pages` pages (`page_cap`), `page_delay` seconds between pages;
- persistent 403/429 -> retry once through Bright Data Web Unlocker when configured,
  otherwise `blocked`.
The endpoint is unofficial: unexpected shapes are reported as `schema_changed`.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlencode

import httpx

from conferge.core.brightdata import BrightDataClient, BrightDataError
from conferge.core.schemas import (
    DiscoveryQuery,
    DiscoveryResult,
    RunReport,
    SourceMode,
    SourceRecord,
    SourceRef,
    Termination,
)
from conferge.events.luma._util import (
    content_hash,
    extract_next_data,
    haversine_km,
    local_date,
    parse_instant,
    prosemirror_text,
    zone,
)

logger = logging.getLogger(__name__)

PROVIDER = "luma"
DISCOVER_URL = "https://api2.luma.com/discover/get-paginated-events"
EVENT_PAGE = "https://luma.com/{slug}"
HEADERS = {
    "Accept": "application/json",
    "Referer": "https://luma.com/",
    "User-Agent": "Mozilla/5.0 (compatible; Conferge/0.1; +https://github.com/spicyx9/PatchConferenceHack)",
}
# Fort Mason, San Francisco (GitHub Universe 2026 venue) -- used only when the query has
# no coordinates; recorded as a warning so the anchor is never implicit.
DEFAULT_LAT, DEFAULT_LON = 37.8060, -122.4320
_RETRYABLE = {429, 500, 502, 503, 504}
_BLOCKING = {403, 429}


class LumaError(RuntimeError):
    """Visible Luma collection failure (no credentials or bodies in the message)."""


class _Blocked(Exception):
    def __init__(self, status: int) -> None:
        super().__init__(f"HTTP {status}")
        self.status = status


class LumaSource:
    """`conferge.core.contracts.Source` implementation for Luma public discovery."""

    provider = PROVIDER

    def __init__(
        self,
        *,
        client: httpx.AsyncClient | None = None,
        brightdata: BrightDataClient | None = None,
        page_limit: int = 50,
        max_pages: int = 60,
        page_delay: float = 0.3,
        retries: int = 2,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._client = client
        self._brightdata = brightdata
        self.page_limit = page_limit
        self.max_pages = max_pages
        self.page_delay = page_delay
        self.retries = retries
        self._sleep = sleep

    # ------------------------------------------------------------------ transport
    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=30.0, headers=HEADERS)
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()

    def _unlocker_ready(self) -> bool:
        bd = self._brightdata
        return bool(bd and bd.unlocker_zone and getattr(bd, "_api_key", None))

    async def _get_text(self, url: str, warnings: list[str]) -> str:
        """GET with bounded retries; on persistent 403/429 try Web Unlocker once."""
        last_status = 0
        for attempt in range(self.retries + 1):
            response = await self._http().get(url, headers=HEADERS)
            last_status = response.status_code
            if response.status_code < 400:
                return response.text
            if response.status_code in _RETRYABLE and attempt < self.retries:
                await self._sleep(min(2**attempt, 4))
                continue
            break
        if last_status in _BLOCKING:
            bd = self._brightdata
            if bd is not None and self._unlocker_ready():
                warnings.append(f"direct HTTP {last_status}; retried via Bright Data Web Unlocker")
                try:
                    return await bd.unlock(url)
                except BrightDataError as exc:
                    warnings.append(f"Web Unlocker failed: {exc}")
            raise _Blocked(last_status)
        raise LumaError(f"Luma HTTP {last_status}")

    # ------------------------------------------------------------------ discover
    async def discover(self, query: DiscoveryQuery) -> DiscoveryResult:
        started = datetime.now(timezone.utc)
        warnings: list[str] = []
        errors: list[str] = []
        lat, lon = query.latitude, query.longitude
        if lat is None or lon is None:
            lat, lon = DEFAULT_LAT, DEFAULT_LON
            warnings.append("no coordinates in query; using Fort Mason anchor 37.8060,-122.4320")

        by_id: dict[str, SourceRecord] = {}
        seen_cursors: set[str] = set()
        cursor: str | None = None
        pages = fetched = 0
        termination: Termination = "error"

        while True:
            if pages >= self.max_pages:
                termination = "page_cap"
                warnings.append(f"stopped at page cap {self.max_pages} while has_more=true")
                break
            params: dict[str, Any] = {
                "latitude": lat, "longitude": lon, "pagination_limit": self.page_limit,
            }
            if cursor:
                params["pagination_cursor"] = cursor
            url = f"{DISCOVER_URL}?{urlencode(params)}"
            try:
                body = await self._get_text(url, warnings)
            except _Blocked as exc:
                termination = "blocked" if exc.status == 403 else "rate_limited"
                errors.append(f"page {pages + 1}: blocked ({exc}); no unlocker configured or it failed")
                break
            except (LumaError, httpx.HTTPError) as exc:
                termination = "error"
                errors.append(f"page {pages + 1}: {type(exc).__name__}: {exc}")
                break
            collected_at = datetime.now(timezone.utc)
            try:
                data = json.loads(body)
            except json.JSONDecodeError:
                termination = "schema_changed"
                errors.append(f"page {pages + 1}: response is not JSON (HTML or block page?)")
                break
            entries = data.get("entries") if isinstance(data, dict) else None
            has_more = data.get("has_more") if isinstance(data, dict) else None
            if not isinstance(entries, list) or not isinstance(has_more, bool):
                termination = "schema_changed"
                keys = sorted(data.keys())[:10] if isinstance(data, dict) else type(data).__name__
                errors.append(f"page {pages + 1}: missing entries/has_more; got {keys}")
                break
            pages += 1
            fetched += len(entries)
            new_ids = 0
            for entry in entries:
                record = self._record(entry, collected_at, pages, warnings)
                if record is None:
                    continue
                if record.source_id not in by_id:
                    new_ids += 1
                by_id[record.source_id] = record
            if not has_more:
                termination = "exhausted"
                break
            next_cursor = data.get("next_cursor")
            if not isinstance(next_cursor, str) or not next_cursor:
                termination = "schema_changed"
                errors.append(f"page {pages}: has_more=true without next_cursor")
                break
            if next_cursor == cursor or next_cursor in seen_cursors:
                termination = "cursor_stuck"
                warnings.append(f"page {pages}: repeated pagination_cursor; stopping")
                break
            if new_ids == 0:
                termination = "cursor_stuck"
                warnings.append(f"page {pages}: has_more=true but no new api_id; stopping")
                break
            seen_cursors.add(next_cursor)
            cursor = next_cursor
            await self._sleep(self.page_delay)

        if pages and fetched == 0:
            warnings.append("zero results returned")
        unique = list(by_id.values())
        items = self._filter(unique, query, lat, lon, warnings)
        if termination == "exhausted":
            status = "ok"
        elif pages > 0:
            status = "degraded"
        else:
            status = "failed"
        report = RunReport(
            provider=PROVIDER,
            started_at=started,
            finished_at=datetime.now(timezone.utc),
            status=status,
            termination=termination,
            source_mode="live",
            fetched_count=fetched,
            unique_count=len(unique),
            pages=pages,
            expected_count=None,  # Luma exposes no total; exhaustion is the only proof
            errors=errors,
            warnings=warnings,
        )
        return DiscoveryResult(items=items, run_report=report, errors=list(errors))

    def _record(
        self, entry: Any, collected_at: datetime, page: int, warnings: list[str],
        source_mode: SourceMode = "live",
    ) -> SourceRecord | None:
        if not isinstance(entry, dict):
            warnings.append(f"page {page}: non-object entry skipped (schema drift)")
            return None
        event = entry.get("event") if isinstance(entry.get("event"), dict) else {}
        api_id = entry.get("api_id") or event.get("api_id")
        if not isinstance(api_id, str) or not api_id:
            warnings.append(f"page {page}: entry without api_id skipped (schema drift)")
            return None
        slug = event.get("url")
        source_url = EVENT_PAGE.format(slug=slug) if isinstance(slug, str) and slug else None
        return SourceRecord(
            provider=PROVIDER,
            source_id=api_id,
            source_mode=source_mode,
            collected_at=collected_at,
            payload=entry,
            source_url=source_url,
            request_id=f"discover-page-{page}",
            content_hash=content_hash(entry),
        )

    @staticmethod
    def _filter(
        records: list[SourceRecord], query: DiscoveryQuery, lat: float, lon: float,
        warnings: list[str],
    ) -> list[SourceRecord]:
        """Client-side filters: local-date window, radius, keywords/categories, limit."""
        keywords = [k.lower() for k in query.keywords]
        categories = query.filters.get("categories") or []
        keywords += [str(c).lower() for c in categories]
        kept: list[SourceRecord] = []
        no_date = 0
        for rec in records:
            event = rec.payload.get("event") or {}
            tz = zone(event.get("timezone"))
            start = local_date(parse_instant(event.get("start_at")), tz)
            end = local_date(parse_instant(event.get("end_at")), tz) or start
            if query.start_date or query.end_date:
                if start is None:
                    no_date += 1
                    continue
                if query.end_date and start > query.end_date:
                    continue
                if query.start_date and (end or start) < query.start_date:
                    continue
            if query.radius_km is not None:
                coord = event.get("coordinate") or {}
                elat, elon = coord.get("latitude"), coord.get("longitude")
                if not isinstance(elat, (int, float)) or not isinstance(elon, (int, float)):
                    continue
                if haversine_km(lat, lon, elat, elon) > query.radius_km:
                    continue
            if keywords:
                haystack = " ".join([
                    str(event.get("name") or ""),
                    str((rec.payload.get("calendar") or {}).get("name") or ""),
                    " ".join(str(h.get("name") or "") for h in rec.payload.get("hosts") or []
                             if isinstance(h, dict)),
                ]).lower()
                if not any(k in haystack for k in keywords):
                    continue
            kept.append(rec)
        if no_date:
            warnings.append(f"{no_date} records without parseable start_at excluded by date filter")
        if len(kept) != len(records):
            warnings.append(f"client-side filters kept {len(kept)} of {len(records)} unique events")
        if len(kept) > query.limit:
            warnings.append(f"result truncated to query.limit={query.limit} of {len(kept)}")
            kept = kept[: query.limit]
        return kept

    # ------------------------------------------------------------------ details
    async def fetch_details(self, ref: SourceRef) -> SourceRecord:
        """Fetch the public event page and parse `__NEXT_DATA__`.

        Hidden ("register to see address") locations stay null. Visible featured guests
        are reduced to name/avatar/bio in `payload.guests_visible` -- partial, never a
        guest list and never attendance evidence for Conferge people.
        """
        if ref.url:
            url = str(ref.url)
        elif ref.source_id and not ref.source_id.startswith("evt-"):
            url = EVENT_PAGE.format(slug=ref.source_id)
        else:
            raise LumaError("fetch_details needs ref.url or an event slug as source_id")
        warnings: list[str] = []
        try:
            html = await self._get_text(url, warnings)
        except _Blocked as exc:
            raise LumaError(f"Luma event page blocked ({exc})") from exc
        collected_at = datetime.now(timezone.utc)
        next_data = extract_next_data(html)
        data = (((next_data or {}).get("props") or {}).get("pageProps") or {}).get(
            "initialData"
        ) or {}
        data = data.get("data") if isinstance(data, dict) else None
        if not isinstance(data, dict) or not isinstance(data.get("event"), dict):
            raise LumaError("Luma event page: __NEXT_DATA__ initialData.data.event missing "
                            "(schema_changed)")
        payload = _detail_payload(data)
        payload["detail_warnings"] = warnings
        api_id = data.get("api_id") or data["event"].get("api_id") or ref.source_id
        return SourceRecord(
            provider=PROVIDER,
            source_id=str(api_id),
            source_mode="live",
            collected_at=collected_at,
            payload=payload,
            source_url=url,
            request_id="event-page",
            content_hash=content_hash(payload),
        )


def _detail_payload(data: dict[str, Any]) -> dict[str, Any]:
    """Keep the discover-compatible keys plus description/categories; drop the rest."""
    keep = (
        "api_id", "event", "calendar", "hosts", "guest_count", "ticket_count", "ticket_info",
        "registration_availability", "categories", "sold_out", "start_at",
    )
    payload = {k: data.get(k) for k in keep if k in data}
    description = prosemirror_text(data.get("description_mirror")).strip()
    payload["description_text"] = description or None
    guests = []
    for guest in data.get("featured_guests") or []:
        if isinstance(guest, dict) and guest.get("name"):
            guests.append({
                "name": guest.get("name"),
                "avatar_url": guest.get("avatar_url"),
                "bio_short": guest.get("bio_short"),
            })
    payload["guests_visible"] = guests
    payload["guests_visible_note"] = (
        "partial featured guests shown publicly by Luma; not a full guest list"
    )
    return payload
