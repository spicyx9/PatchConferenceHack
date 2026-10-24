"""reinventradar.com/schedule parser (best effort, independent implementation).

The page is a Next.js app; its React Server Component stream
(self.__next_f.push chunks) embeds an "events" array with ISO 8601 start/end
instants carrying a UTC offset. Nothing found = schema_changed.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any

from conferge.core.schemas import SourceMode
from conferge.events.aggregators.common import (
    ParseOutcome,
    make_record,
    rsvp_platform,
    safe_url,
)

PROVIDER = "reinventradar"
PAGE_URL = "https://www.reinventradar.com/schedule"

_CHUNK_RE = re.compile(r"self\.__next_f\.push\(\[1,\s*(\"(?:[^\"\\]|\\.)*\")\]\)", re.S)
_EVENT_KEYS = {"title", "start_at"}


def _rsc_stream(html: str) -> str:
    parts: list[str] = []
    for literal in _CHUNK_RE.findall(html):
        try:
            parts.append(json.loads(literal))
        except json.JSONDecodeError:
            continue
    return "".join(parts)


def extract_events(html: str) -> list[dict[str, Any]] | None:
    """Return the first JSON array under an "events" key whose items look like events."""
    stream = _rsc_stream(html)
    decoder = json.JSONDecoder()
    for match in re.finditer(r'"events"\s*:\s*\[', stream):
        try:
            value, _ = decoder.raw_decode(stream, match.end() - 1)
        except json.JSONDecodeError:
            continue
        if isinstance(value, list) and value and all(
            isinstance(item, dict) and _EVENT_KEYS <= item.keys() for item in value
        ):
            return value
    return None


def parse_page(
    html: str, *, collected_at: datetime, source_mode: SourceMode, url: str = PAGE_URL,
    slug: str = "reinventradar",
) -> ParseOutcome:
    outcome = ParseOutcome()
    events = extract_events(html)
    if events is None:
        outcome.termination = "schema_changed"
        outcome.errors.append("no events array found in Next.js payload")
        return outcome
    for index, item in enumerate(events):
        title = (item.get("title") or "").strip()
        if not title:
            outcome.warnings.append(f"event_without_title:{index}")
            continue
        outcome.raw_rows += 1
        rsvp_url = safe_url(item.get("registration_url"))
        payload: dict[str, Any] = {
            "site": PROVIDER,
            "slug": slug,
            "page_url": url,
            "row_index": index,
            "radar_id": item.get("id"),
            "title": title,
            "host": item.get("host_company"),
            "categories": list(item.get("categories") or []),
            "host_categories": list(item.get("hostCategories") or []),
            "focus": list(item.get("focus") or []),
            "day": item.get("day"),
            "start_at_raw": item.get("start_at"),
            "end_at_raw": item.get("end_at"),
            "location_text": item.get("venue"),
            "address": item.get("address"),
            "rsvp_url": rsvp_url,
            "rsvp_platform": rsvp_platform(rsvp_url),
            "listing_source_url": safe_url(item.get("source_url")),
        }
        if not payload["day"] and not payload["start_at_raw"]:
            outcome.warnings.append(f"row_without_day:{title!r}")
        source_id = f"radar:{item.get('id')}" if item.get("id") is not None else f"radar:{index}"
        outcome.records.append(make_record(
            PROVIDER, source_id, payload, source_mode=source_mode,
            collected_at=collected_at, source_url=url,
        ))
    if not outcome.records:
        outcome.warnings.append("empty_page")
    return outcome
