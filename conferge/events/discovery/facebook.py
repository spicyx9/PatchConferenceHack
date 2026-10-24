"""Facebook Events discovery through the Bright Data Web Scraper API dataset.

Dataset `gd_m14sd0to1jz48ppm51` (Facebook events). Two discovery inputs are supported:

- `query.filters["facebook_page_urls"]`: sponsor or organizer page URLs, sent with
  method `discover_by_url` and inputs `[{"url": <page url>}]`;
- `query.city` (+ optional `start_date` / `end_date`), sent with method
  `discover_by_location` and inputs `[{"location": city, "date_from": iso, "date_to": iso}]`.

UNVERIFIED: the exact input field names of `discover_by_location` (`location`,
`date_from`, `date_to`) and the output row field names have not been checked against a
live response (no Bright Data key tonight). `normalize` therefore reads several candidate
keys defensively and leaves anything missing as None.

Rules: no fixture fallback ever; a missing key, a missing client or a Bright Data error
yields a visible `failed` RunReport with zero items. Error rows returned because of
`include_errors=true` are counted as warnings, never as items. Zero rows is `degraded`.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any

from pydantic import HttpUrl, TypeAdapter, ValidationError

from conferge.core.brightdata import BrightDataClient, BrightDataError, CollectionOutput
from conferge.core.schemas import (
    DiscoveryQuery,
    DiscoveryResult,
    Event,
    RunReport,
    RunStatus,
    SourceEvidence,
    SourceRecord,
    SourceRef,
    Termination,
    Venue,
)

PROVIDER = "facebook_events"
DATASET_ID = "gd_m14sd0to1jz48ppm51"
_URL = TypeAdapter(HttpUrl)
_MAX_ERROR_LEN = 200


class FacebookEventsError(RuntimeError):
    """Visible Facebook Events collection failure (sanitized, no credentials)."""


def _sanitize(exc: BaseException) -> str:
    text = f"{type(exc).__name__}: {exc}"
    text = re.sub(r"(?i)bearer\s+\S+", "Bearer ***", text)
    return text[:_MAX_ERROR_LEN]


def _valid_url(value: Any) -> str | None:
    if not isinstance(value, str) or not value.startswith(("http://", "https://")):
        return None
    try:
        return str(_URL.validate_python(value))
    except ValidationError:
        return None


def _is_error_row(row: dict[str, Any]) -> bool:
    return bool(row.get("error") or row.get("error_code"))


def _row_id(row: dict[str, Any]) -> str | None:
    for key in ("event_id", "id"):
        value = row.get(key)
        if isinstance(value, (str, int)) and not isinstance(value, bool) and str(value):
            return str(value)
    url = row.get("url") or row.get("event_url")
    if isinstance(url, str) and url:
        return url
    return None


class FacebookEventsSource:
    """`conferge.core.contracts.Source` implementation for Bright Data Facebook events."""

    provider = PROVIDER

    def __init__(
        self,
        brightdata: BrightDataClient | None,
        *,
        limit_per_input: int = 50,
        poll_interval: float = 5.0,
        max_polls: int = 24,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._brightdata = brightdata
        self.limit_per_input = limit_per_input
        self.poll_interval = poll_interval
        self.max_polls = max_polls
        self._sleep = sleep

    # ------------------------------------------------------------------ helpers
    def _client(self) -> BrightDataClient:
        bd = self._brightdata
        if bd is None:
            raise FacebookEventsError("no Bright Data client configured")
        if not getattr(bd, "_api_key", None):
            raise FacebookEventsError("Bright Data key missing; set BRIGHTDATA_API_KEY")
        return bd

    @staticmethod
    def _plans(query: DiscoveryQuery) -> list[tuple[str, list[dict[str, Any]]]]:
        plans: list[tuple[str, list[dict[str, Any]]]] = []
        raw_urls = query.filters.get("facebook_page_urls") or []
        if isinstance(raw_urls, str):
            raw_urls = [raw_urls]
        urls = [u for u in raw_urls if isinstance(u, str) and u.strip()]
        if urls:
            plans.append(("discover_by_url", [{"url": u.strip()} for u in urls]))
        if query.city:
            # UNVERIFIED input field names for discover_by_location (see module docstring).
            location: dict[str, Any] = {"location": query.city}
            if query.start_date:
                location["date_from"] = query.start_date.isoformat()
            if query.end_date:
                location["date_to"] = query.end_date.isoformat()
            plans.append(("discover_by_location", [location]))
        return plans

    async def _collect(
        self, bd: BrightDataClient, method: str, inputs: list[dict[str, Any]],
    ) -> tuple[CollectionOutput, bool]:
        """Run one dataset call; returns (output, finished). Polls snapshots if needed."""
        output = await bd.scrape_dataset(
            DATASET_ID, inputs, method=method, limit_per_input=self.limit_per_input,
        )
        if output.status != "running":
            return output, True
        snapshot_id = output.snapshot_id
        if not snapshot_id:
            raise FacebookEventsError("Bright Data running without snapshot_id")
        for _ in range(self.max_polls):
            await self._sleep(self.poll_interval)
            output = await bd.snapshot_results(snapshot_id)
            if output.status != "running":
                return output, True
        return output, False

    @staticmethod
    def _rows(data: Any) -> list[Any] | None:
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return [data]
        if data is None:
            return []
        return None

    # ------------------------------------------------------------------ discover
    async def discover(self, query: DiscoveryQuery) -> DiscoveryResult:
        started = datetime.now(timezone.utc)
        warnings: list[str] = []
        errors: list[str] = []
        by_id: dict[str, SourceRecord] = {}
        fetched = pages = error_rows = 0
        truncated = still_running = schema_changed = False

        def report(status: RunStatus, termination: Termination) -> DiscoveryResult:
            items = list(by_id.values())
            rr = RunReport(
                provider=PROVIDER, started_at=started, finished_at=datetime.now(timezone.utc),
                status=status, termination=termination, source_mode="live",
                fetched_count=max(fetched, len(items)), unique_count=len(items), pages=pages,
                errors=errors, warnings=warnings,
            )
            return DiscoveryResult(items=items, run_report=rr, errors=list(errors))

        plans = self._plans(query)
        if not plans:
            errors.append("no inputs: set filters.facebook_page_urls and/or query.city")
            return report("failed", "error")
        try:
            bd = self._client()
        except FacebookEventsError as exc:
            errors.append(_sanitize(exc))
            return report("failed", "error")

        for method, inputs in plans:
            try:
                output, finished = await self._collect(bd, method, inputs)
            except (BrightDataError, FacebookEventsError) as exc:
                errors.append(f"{method}: {_sanitize(exc)}")
                continue
            pages += 1
            if not finished:
                still_running = True
                warnings.append(
                    f"{method}: snapshot still running after {self.max_polls} polls "
                    f"(snapshot_id={output.snapshot_id})"
                )
                continue
            rows = self._rows(output.data)
            if rows is None:
                schema_changed = True
                errors.append(f"{method}: unexpected payload type {type(output.data).__name__}")
                continue
            collected_at = datetime.now(timezone.utc)
            valid_rows = 0
            for row in rows:
                if not isinstance(row, dict):
                    warnings.append(f"{method}: non-object row skipped (schema drift)")
                    continue
                if _is_error_row(row):
                    error_rows += 1
                    code = row.get("error_code") or "error"
                    warnings.append(f"{method}: error row ({str(code)[:60]})")
                    continue
                fetched += 1
                valid_rows += 1
                source_id = _row_id(row)
                if source_id is None:
                    warnings.append(f"{method}: row without event_id/id/url skipped")
                    continue
                by_id[source_id] = SourceRecord(
                    provider=PROVIDER, source_id=source_id, source_mode="live",
                    collected_at=collected_at, payload=row,
                    source_url=_valid_url(row.get("url") or row.get("event_url")),
                    request_id=output.snapshot_id,
                )
            if valid_rows >= self.limit_per_input * len(inputs):
                truncated = True
                warnings.append(
                    f"{method}: {valid_rows} rows reached limit_per_input="
                    f"{self.limit_per_input}; results may be truncated"
                )

        if len(by_id) > query.limit:
            truncated = True
            warnings.append(f"result truncated to query.limit={query.limit} of {len(by_id)}")
            by_id = dict(list(by_id.items())[: query.limit])

        if pages == 0:
            return report("failed", "error")
        if errors:
            return report("degraded", "schema_changed" if schema_changed else "error")
        if still_running:
            warnings.append("snapshot still running")
            return report("degraded", "error")
        if not by_id:
            warnings.append("zero results returned")
            return report("degraded", "error")
        if truncated:
            return report("degraded", "page_cap")
        if error_rows:
            return report("degraded", "error")
        return report("ok", "exhausted")

    # ------------------------------------------------------------------ details
    async def fetch_details(self, ref: SourceRef) -> SourceRecord:
        if ref.url is None:
            raise FacebookEventsError("fetch_details needs ref.url")
        bd = self._client()
        url = str(ref.url)
        try:
            output, finished = await self._collect(bd, "collect_by_url", [{"url": url}])
        except BrightDataError as exc:
            raise FacebookEventsError(_sanitize(exc)) from exc
        if not finished:
            raise FacebookEventsError("snapshot still running")
        rows = [r for r in (self._rows(output.data) or []) if isinstance(r, dict)]
        good = [r for r in rows if not _is_error_row(r)]
        if not good:
            raise FacebookEventsError("Bright Data returned no event row for this URL")
        row = good[0]
        return SourceRecord(
            provider=PROVIDER, source_id=_row_id(row) or ref.source_id, source_mode="live",
            collected_at=datetime.now(timezone.utc), payload=row,
            source_url=_valid_url(row.get("url") or row.get("event_url")) or url,
            request_id=output.snapshot_id,
        )


# ---------------------------------------------------------------------- normalize
def _first(payload: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = payload.get(key)
        if value not in (None, "", [], {}):
            return value
    return None


def _text(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _aware(value: Any) -> datetime | None:
    """Parse an ISO string with an explicit offset; naive strings give None (no tz guess)."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        seconds = value / 1000 if value > 10**11 else value
        try:
            return datetime.fromtimestamp(seconds, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip())
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


def _count(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, float) and value.is_integer() and value >= 0:
        return int(value)
    if isinstance(value, str):
        cleaned = value.strip().replace(",", "")
        if cleaned.isdigit():
            return int(cleaned)
    return None


def _coord(value: Any, low: float, high: float) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if low <= number <= high else None


def _venue(payload: dict[str, Any]) -> Venue | None:
    raw = _first(payload, "location", "place", "address")
    if raw is None:
        return None
    if isinstance(raw, str):
        name = _text(raw)
        return Venue(name=name) if name else None
    if not isinstance(raw, dict):
        return None
    address = raw.get("address") or raw.get("street")
    if isinstance(address, dict):
        address = address.get("street") or address.get("full_address")
    city = raw.get("city")
    if isinstance(city, dict):
        city = city.get("name")
    lat = _coord(raw.get("latitude", raw.get("lat")), -90, 90)
    lng = _coord(raw.get("longitude", raw.get("lng", raw.get("lon"))), -180, 180)
    if lat is None or lng is None:
        lat = lng = None
    venue = Venue(
        name=_text(raw.get("name")), address=_text(address), city=_text(city),
        latitude=lat, longitude=lng,
        coordinate_precision="exact" if lat is not None else "unknown",
    )
    if not any([venue.name, venue.address, venue.city, venue.latitude is not None]):
        return None
    return venue


def _names(value: Any) -> list[str]:
    items = value if isinstance(value, list) else [value]
    names: list[str] = []
    for item in items:
        name = _text(item.get("name")) if isinstance(item, dict) else _text(item)
        if name and name not in names:
            names.append(name)
    return names


def _event_type(title: str) -> str:
    lowered = title.lower()
    if re.search(r"\b(after\s*-?\s*party|party|happy\s+hour)\b", lowered):
        return "party"
    if re.search(r"\bmeet\s*-?\s*up\b", lowered):
        return "meetup"
    if re.search(r"\bworkshop\b", lowered):
        return "workshop"
    return "other"  # hackathons and everything else stay "other"


def normalize(record: SourceRecord, *, conference_id: str | None = None) -> Event:
    """Map a Bright Data Facebook event row to `Event`. Missing data stays None.

    Timezone decision: `Event.timezone` is set only when the payload carries an IANA name
    (a "timezone" string containing "/"). No timezonefinder dependency is available, and
    deriving a zone from coordinates or the city would be an invention.
    `conference_relation` is always "unknown": linking to a conference happens elsewhere.
    """
    payload = record.payload
    title = _text(_first(payload, "name", "title", "event_name"))
    if title is None:
        raise ValueError(f"facebook event {record.source_id}: no title in payload")
    start_at = _aware(_first(payload, "start_date", "start_time", "date"))
    end_at = _aware(_first(payload, "end_date", "end_time"))
    if start_at and end_at and end_at < start_at:
        end_at = None
    tz = payload.get("timezone")
    canceled = _first(payload, "is_canceled", "isCanceled", "is_cancelled")
    source_url = _valid_url(_first(payload, "url", "event_url")) or (
        str(record.source_url) if record.source_url else None
    )
    evidence = SourceEvidence(
        provider=record.provider, source_mode=record.source_mode, source_url=source_url,
        collected_at=record.collected_at, source_record_id=record.source_id,
        raw_ref=record.request_id,
    )
    return Event(
        id=f"evt:facebook:{record.source_id}",
        conference_id=conference_id,
        title=title,
        description=_text(payload.get("description")),
        event_type=_event_type(title),
        start_at=start_at,
        end_at=end_at,
        timezone=tz if isinstance(tz, str) and "/" in tz else None,
        venue=_venue(payload),
        organizer_names=_names(_first(payload, "hosts", "organizers", "host")),
        status="cancelled" if canceled is True else "unknown",
        conference_relation="unknown",
        registration_url=_valid_url(_first(payload, "ticket_url", "ticketUrl")),
        source_url=source_url,
        registered_count=_count(_first(payload, "users_responded", "usersResponded", "going")),
        evidence=[evidence],
    )
