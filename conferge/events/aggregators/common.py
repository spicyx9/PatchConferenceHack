"""Shared helpers for conference-party aggregator parsers.

Independent implementation (no third-party code copied). Rules enforced here:
a missing date stays None (never today's date), a missing timezone leaves
clock times unresolved, and every record keeps its page URL and collected_at.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from urllib.parse import urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from conferge.core.schemas import RunReport, SourceMode, SourceRecord, SourceRef, Termination

BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/129.0 Safari/537.36"
)

# Known slugs: city and IANA zone of the conference. Unknown slugs need
# query.filters["timezone"], otherwise clock times stay None.
SLUG_CONTEXT: dict[str, dict[str, str]] = {
    "github26": {"city": "San Francisco", "timezone": "America/Los_Angeles"},
    "reinvent2026": {"city": "Las Vegas", "timezone": "America/Los_Angeles"},
    "sema-2026": {"city": "Las Vegas", "timezone": "America/Los_Angeles"},
}

_PLATFORM_HOSTS = {
    "luma.com": "luma",
    "lu.ma": "luma",
    "eventbrite.com": "eventbrite",
    "meetup.com": "meetup",
    "partiful.com": "partiful",
}

MONTHS = {
    name: index
    for index, name in enumerate(
        ["january", "february", "march", "april", "may", "june", "july", "august",
         "september", "october", "november", "december"],
        start=1,
    )
}
MONTHS.update({name[:3]: index for name, index in list(MONTHS.items())})

_TIME_TOKEN = r"(\d{1,2})(?::(\d{2}))?\s*([AaPp]\.?[Mm]\.?)?"
_RANGE_RE = re.compile(rf"^\s*{_TIME_TOKEN}\s*(?:[-\u2013\u2014]|to)\s*{_TIME_TOKEN}\s*$")
_SINGLE_RE = re.compile(rf"^\s*{_TIME_TOKEN}\s*$")


def rsvp_platform(url: str | None) -> str | None:
    """Route an RSVP link to the connector that can enrich it."""
    if not url:
        return None
    host = (urlparse(url).hostname or "").lower()
    for suffix, platform in _PLATFORM_HOSTS.items():
        if host == suffix or host.endswith("." + suffix):
            return platform
    return "aggregator"


def resolve_zone(name: str | None) -> ZoneInfo | None:
    if not name:
        return None
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return None


def _to_24h(hour: int, minute: int, meridiem: str | None) -> time | None:
    if minute > 59:
        return None
    if meridiem is None:
        return time(hour, minute) if 0 <= hour <= 23 else None
    if not 1 <= hour <= 12:
        return None
    pm = meridiem.lower().startswith("p")
    return time((hour % 12) + (12 if pm else 0), minute)


def parse_time_range(text: str | None) -> tuple[time | None, time | None]:
    """Parse '5:30-7:30PM', '7PM-1AM', '2:30-7PM', '7:00 PM - 1:00 AM' (hyphen or en dash).

    A start without meridiem inherits the end meridiem, unless that would put
    the start after the end on a same-day reading (then the other meridiem).
    Unparseable text returns (None, None): never a guessed time.
    """
    if not text:
        return None, None
    cleaned = text.replace("\xa0", " ").strip()
    match = _RANGE_RE.match(cleaned)
    if match:
        h1, m1, mer1, h2, m2, mer2 = match.groups()
        end = _to_24h(int(h2), int(m2 or 0), mer2)
        if end is None:
            return None, None
        if mer1 is None and mer2 is not None:
            start = _to_24h(int(h1), int(m1 or 0), mer2)
            if start is not None and start > end:
                # 11-1PM means 11AM; 10-2AM means 10PM crossing midnight.
                flipped = "am" if mer2.lower().startswith("p") else "pm"
                start = _to_24h(int(h1), int(m1 or 0), flipped)
        else:
            start = _to_24h(int(h1), int(m1 or 0), mer1)
        return start, end
    match = _SINGLE_RE.match(cleaned)
    if match:
        h1, m1, mer1 = match.groups()
        return _to_24h(int(h1), int(m1 or 0), mer1), None
    return None, None


def combine(
    day: date | None, start: time | None, end: time | None, zone: ZoneInfo | None
) -> tuple[datetime | None, datetime | None]:
    """Build aware datetimes; an end before the start rolls to the next day."""
    if day is None or zone is None or start is None:
        return None, None
    start_at = datetime.combine(day, start, tzinfo=zone)
    end_at = None
    if end is not None:
        end_at = datetime.combine(day, end, tzinfo=zone)
        if end_at <= start_at:
            end_at += timedelta(days=1)
    return start_at, end_at


def parse_month_day(text: str | None, reference: date | None) -> date | None:
    """Parse an 'Added'/'Listed' M/D cell; the year comes from the event day.

    A listing date cannot be after the event, so a result past the reference
    day is moved to the previous year. Without a reference year: None.
    """
    if not text or reference is None:
        return None
    match = re.fullmatch(r"\s*(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\s*", text)
    if not match:
        return None
    month, day_num, year_text = match.groups()
    year = reference.year
    if year_text:
        year = int(year_text) + (2000 if len(year_text) == 2 else 0)
    try:
        listed = date(year, int(month), int(day_num))
    except ValueError:
        return None
    if not year_text and listed > reference:
        try:
            listed = listed.replace(year=year - 1)
        except ValueError:
            return None
    return listed


def stable_id(*parts: str | None) -> str:
    joined = "|".join(part or "" for part in parts)
    return hashlib.sha1(joined.encode("utf-8")).hexdigest()[:16]


def content_hash(payload: dict[str, Any]) -> str:
    items = sorted((k, str(v)) for k, v in payload.items() if k != "collected_at")
    return hashlib.sha256(repr(items).encode("utf-8")).hexdigest()


def safe_url(value: str | None) -> str | None:
    if not value:
        return None
    value = value.strip()
    if not value.startswith(("http://", "https://")):
        return None
    return value


def make_record(
    provider: str, source_id: str, payload: dict[str, Any], *, source_mode: SourceMode,
    collected_at: datetime, source_url: str | None,
) -> SourceRecord:
    return SourceRecord(
        provider=provider,
        source_id=source_id,
        source_mode=source_mode,
        collected_at=collected_at,
        payload=payload,
        source_url=safe_url(source_url),
        content_hash=content_hash(payload),
    )


@dataclass
class ParseOutcome:
    """Result of parsing one aggregator page before it becomes a RunReport."""

    records: list[SourceRecord] = field(default_factory=list)
    termination: Termination = "exhausted"
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    raw_rows: int = 0


def build_report(
    provider: str, started_at: datetime, outcome: ParseOutcome, *, source_mode: SourceMode,
    pages: int, ok_on_empty: bool = False,
) -> RunReport:
    unique = len({record.source_id for record in outcome.records})
    complete = outcome.termination in {"exhausted", "not_applicable"}
    if not complete:
        status = "degraded" if outcome.records else "failed"
    elif outcome.records or ok_on_empty:
        status = "ok" if not outcome.errors else "degraded"
    else:
        status = "degraded"
    return RunReport(
        provider=provider,
        started_at=started_at,
        finished_at=max(datetime.now(timezone.utc), started_at),
        status=status,
        termination=outcome.termination,
        source_mode=source_mode,
        fetched_count=max(outcome.raw_rows, len(outcome.records)),
        unique_count=unique,
        pages=pages,
        errors=list(outcome.errors),
        warnings=list(outcome.warnings),
    )


def termination_for_status(status_code: int) -> Termination:
    if status_code in {401, 403}:
        return "blocked"
    if status_code == 429:
        return "rate_limited"
    return "error"


def rsvp_refs(records: list[SourceRecord]) -> list[SourceRef]:
    """RSVP links routed to platform connectors (luma, eventbrite, ...) for enrichment."""
    refs: list[SourceRef] = []
    seen: set[str] = set()
    for record in records:
        url = safe_url(record.payload.get("rsvp_url"))
        platform = record.payload.get("rsvp_platform")
        if not url or platform in {None, "aggregator"} or url in seen:
            continue
        seen.add(url)
        refs.append(SourceRef(provider=platform, source_id=url, url=url))
    return refs
