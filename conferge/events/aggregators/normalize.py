"""Aggregator SourceRecord -> Event normalization.

Missing values stay None. An aggregator listing makes an event a *candidate*
for the anchor conference (evidence: the listing URL), never confirmed.
Cross-source merges are deferred to integration; provenance is kept on each Event.
"""

from __future__ import annotations

import re
from datetime import datetime, time
from typing import Any

from pydantic import ValidationError

from conferge.core.schemas import Event, SourceEvidence, SourceRecord, Venue
from conferge.events.aggregators.common import (
    SLUG_CONTEXT,
    combine,
    parse_month_day,
    parse_time_range,
    resolve_zone,
    safe_url,
)

_PARTY_KINDS = {"party", "happy-hour", "happy_hour", "reception", "cocktail_party", "lounge"}
_SIDE_KINDS = {"dinner", "breakfast", "lunch", "run", "roundtable", "brunch"}
_PARTY_TITLE = re.compile(r"party|happy hour|afterparty|after party|social|bash|mixer", re.I)
_WORKSHOP_TITLE = re.compile(r"workshop|hands-on|lab\b", re.I)
_SPLIT_HOSTS = re.compile(r"\s*(?:,|&|\band\b|\bwith\b|\bx\b)\s*", re.I)


def split_hosts(value: str | None) -> list[str]:
    if not value:
        return []
    cleaned = re.sub(r"\([^)]*\)", "", value)
    return [part.strip() for part in _SPLIT_HOSTS.split(cleaned) if part and part.strip()]


def _event_type(kinds: list[str], title: str) -> str:
    lowered = {kind.lower() for kind in kinds if kind}
    if lowered & _PARTY_KINDS:
        return "party"
    if "meetup" in lowered:
        return "meetup"
    if "workshop" in lowered:
        return "workshop"
    if lowered & _SIDE_KINDS:
        return "side_event"
    if _WORKSHOP_TITLE.search(title):
        return "workshop"
    if _PARTY_TITLE.search(title):
        return "party"
    return "side_event"


def _context(payload: dict[str, Any], timezone_name: str | None, city: str | None):
    slug_ctx = SLUG_CONTEXT.get(payload.get("slug") or "", {})
    zone_name = timezone_name or slug_ctx.get("timezone")
    return resolve_zone(zone_name), (city or slug_ctx.get("city"))


def _venue_from_lines(lines: list[str], hidden: bool, city: str | None) -> Venue | None:
    if hidden or not lines:
        return Venue(city=city) if city else None
    name = lines[0]
    address = ", ".join(lines[1:]) or None
    return Venue(name=name, address=address, city=city)


def normalize_record(
    record: SourceRecord, *, conference_id: str | None = None,
    timezone_name: str | None = None, city: str | None = None,
) -> Event:
    payload = record.payload
    zone, city = _context(payload, timezone_name, city)
    title = payload.get("title") or record.source_id
    day_text = payload.get("day")
    day = None
    if day_text:
        try:
            day = datetime.fromisoformat(day_text).date()
        except ValueError:
            day = None

    start, end = parse_time_range(payload.get("time_text"))
    start_at, end_at = combine(day, start, end, zone)
    venue = _venue_from_lines(
        payload.get("location_lines") or [], bool(payload.get("address_hidden")), city
    )
    hosts = split_hosts(payload.get("sponsor"))
    kinds: list[str] = []

    first_listed_at = None
    listed = parse_month_day(payload.get("added_text"), day)
    if listed is not None and zone is not None:
        # Source gives a calendar date only; local midnight marks date precision.
        first_listed_at = datetime.combine(listed, time(0, 0), tzinfo=zone)

    listing_url = safe_url(payload.get("page_url")) or (
        str(record.source_url) if record.source_url else None
    )
    relation_evidence = [f"listed_on_aggregator:{listing_url}"] if listing_url else []
    evidence = [SourceEvidence(
        provider=record.provider,
        source_mode=record.source_mode,
        source_url=listing_url,
        collected_at=record.collected_at,
        source_record_id=record.source_id,
    )]
    return Event(
        id=f"{record.provider}:{record.source_id}",
        conference_id=conference_id,
        title=title,
        event_type=_event_type(kinds, title),
        start_at=start_at,
        end_at=end_at,
        timezone=zone.key if zone is not None else None,
        venue=venue,
        organizer_names=hosts,
        topics=list(payload.get("focus") or []),
        status="unknown",
        conference_relation="candidate" if conference_id and relation_evidence else "unknown",
        relation_evidence=relation_evidence if conference_id else [],
        registration_url=safe_url(payload.get("rsvp_url")),
        source_url=listing_url,
        first_listed_at=first_listed_at,
        evidence=evidence,
    )


def normalize_records(
    records: list[SourceRecord], *, conference_id: str | None = None,
    timezone_name: str | None = None, city: str | None = None,
) -> tuple[list[Event], list[str]]:
    """Normalize all records; a record that fails validation is reported, not dropped silently."""
    events: list[Event] = []
    errors: list[str] = []
    for record in records:
        try:
            events.append(normalize_record(
                record, conference_id=conference_id, timezone_name=timezone_name, city=city
            ))
        except (ValidationError, ValueError) as exc:
            errors.append(f"normalize {record.provider}:{record.source_id}: {exc.__class__.__name__}")
    return events, errors
