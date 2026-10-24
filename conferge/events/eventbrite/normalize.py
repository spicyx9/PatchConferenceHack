"""Eventbrite destination_event payload -> Event normalization.

Times come from start_date/start_time in the event's IANA timezone; a hidden
or missing date stays None (never today's date). Prices are copied from
ticket_availability major_value strings, never computed.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import ValidationError

from conferge.core.schemas import Event, SourceEvidence, SourceRecord, Venue

_FORMAT_TYPES = {
    "party or social gathering": "party",
    "networking event": "meetup",
    "meeting or networking event": "meetup",
    "class, training, or workshop": "workshop",
    "conference": "conference",
    "seminar or talk": "session",
}


def payload_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


def _zone(name: Any) -> ZoneInfo | None:
    if not isinstance(name, str) or not name:
        return None
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return None


def local_datetime(day: Any, clock: Any, zone: ZoneInfo | None) -> datetime | None:
    """Combine 'YYYY-MM-DD' and 'HH:MM' in the event zone; anything missing gives None."""
    if not isinstance(day, str) or not isinstance(clock, str) or zone is None:
        return None
    try:
        naive = datetime.fromisoformat(f"{day}T{clock}")
    except ValueError:
        return None
    return naive.replace(tzinfo=zone)


def _money(value: Any) -> str | None:
    if value is None:
        return None
    try:
        amount = Decimal(str(value))
    except InvalidOperation:
        return None
    if not amount.is_finite() or amount < 0:
        return None
    text = format(amount, "f")
    # Keep the source string ("25.00"); MoneyString allows at most 4 decimals.
    return text if re.fullmatch(r"[0-9]+(?:\.[0-9]{1,4})?", text) else None


def _coordinate(value: Any) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _venue(item: dict[str, Any]) -> Venue | None:
    raw = item.get("primary_venue")
    if not isinstance(raw, dict):
        return None
    address = raw.get("address") if isinstance(raw.get("address"), dict) else {}
    lat, lon = _coordinate(address.get("latitude")), _coordinate(address.get("longitude"))
    valid = lat is not None and lon is not None and -90 <= lat <= 90 and -180 <= lon <= 180
    return Venue(
        name=raw.get("name") or None,
        address=address.get("localized_address_display") or address.get("address_1") or None,
        city=address.get("city") or None,
        latitude=lat if valid else None,
        longitude=lon if valid else None,
        coordinate_precision="exact" if valid else "unknown",
    )


def _event_type(tags: list[dict[str, Any]]) -> str:
    for tag in tags:
        if tag.get("prefix") == "EventbriteFormat":
            mapped = _FORMAT_TYPES.get(str(tag.get("display_name", "")).lower())
            if mapped:
                return mapped
    return "other"


def _published(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else None


def normalize_record(record: SourceRecord, *, conference_id: str | None = None) -> Event:
    item = record.payload
    zone = _zone(item.get("timezone"))
    start_at = None if item.get("hide_start_date") else local_datetime(
        item.get("start_date"), item.get("start_time"), zone
    )
    end_at = None if item.get("hide_end_date") else local_datetime(
        item.get("end_date"), item.get("end_time"), zone
    )
    if start_at and end_at and end_at < start_at:
        end_at = None
    tags = [tag for tag in item.get("tags") or [] if isinstance(tag, dict)]
    tickets = item.get("ticket_availability") if isinstance(
        item.get("ticket_availability"), dict
    ) else {}
    low = tickets.get("minimum_ticket_price") if isinstance(
        tickets.get("minimum_ticket_price"), dict
    ) else {}
    high = tickets.get("maximum_ticket_price") if isinstance(
        tickets.get("maximum_ticket_price"), dict
    ) else {}
    price_min, price_max = _money(low.get("major_value")), _money(high.get("major_value"))
    currency = low.get("currency") or high.get("currency")
    if price_min is None and price_max is None:
        currency = None
    if isinstance(currency, str) and len(currency) != 3:
        currency = None
    organizer = item.get("primary_organizer") if isinstance(
        item.get("primary_organizer"), dict
    ) else {}
    if item.get("is_cancelled"):
        status = "cancelled"
    elif tickets.get("is_sold_out"):
        status = "sold_out"
    else:
        status = "scheduled"
    url = record.source_url
    topics = sorted({
        str(tag.get("display_name")) for tag in tags
        if tag.get("prefix") in {"EventbriteCategory", "EventbriteSubCategory"}
        and tag.get("display_name")
    })
    return Event(
        id=f"eventbrite:{record.source_id}",
        conference_id=conference_id,
        title=item.get("name") or record.source_id,
        description=item.get("summary") or item.get("full_description") or None,
        event_type=_event_type(tags),
        start_at=start_at,
        end_at=end_at,
        timezone=zone.key if zone else None,
        venue=None if item.get("is_online_event") else _venue(item),
        organizer_ids=[f"eventbrite-organizer:{organizer['id']}"] if organizer.get("id") else [],
        organizer_names=[organizer["name"]] if organizer.get("name") else [],
        topics=topics,
        status=status,
        conference_relation="unknown",
        registration_url=url,
        source_url=url,
        is_free=tickets.get("is_free") if isinstance(tickets.get("is_free"), bool) else None,
        price_min=price_min,
        price_max=price_max,
        currency=currency if (price_min or price_max) else None,
        first_listed_at=_published(item.get("published")),
        evidence=[SourceEvidence(
            provider="eventbrite", source_mode=record.source_mode, source_url=url,
            collected_at=record.collected_at, source_record_id=record.source_id,
        )],
    )


def normalize_records(
    records: list[SourceRecord], *, conference_id: str | None = None
) -> tuple[list[Event], list[str]]:
    events: list[Event] = []
    errors: list[str] = []
    for record in records:
        try:
            events.append(normalize_record(record, conference_id=conference_id))
        except (ValidationError, ValueError) as exc:
            errors.append(f"normalize eventbrite:{record.source_id}: {exc.__class__.__name__}")
    return events, errors
