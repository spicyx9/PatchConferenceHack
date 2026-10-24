"""Luma `SourceRecord` -> `conferge.core.schemas.Event`.

Only facts present in the payload are mapped; everything else stays None/"unknown".
Conference relation is left "unknown": nearby-in-time-and-place is decided downstream
and never upgraded to confirmed here.
"""

from __future__ import annotations

from typing import Any

from conferge.core.schemas import Event, SourceEvidence, SourceRecord, Venue
from conferge.events.luma._util import cents_to_money, localize, parse_instant, zone


def _venue(event: dict[str, Any]) -> Venue | None:
    geo = event.get("geo_address_info") if isinstance(event.get("geo_address_info"), dict) else {}
    coord = event.get("coordinate") if isinstance(event.get("coordinate"), dict) else {}
    lat, lon = coord.get("latitude"), coord.get("longitude")
    if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
        lat = lon = None
    if not geo and lat is None:
        return None
    shown = geo.get("mode") == "shown" and event.get("geo_address_visibility") in {None, "public"}
    if shown:
        precision = "exact" if lat is not None else "unknown"
        address = geo.get("full_address") or geo.get("address") or None
    else:
        # "register to see address": Luma fuzzes the pin; never surface it as exact.
        precision = "approximate" if lat is not None else ("city" if geo.get("city") else "unknown")
        address = None
    name = geo.get("address") if shown else None
    return Venue(
        name=name or None,
        address=address,
        city=geo.get("city") or None,
        latitude=lat,
        longitude=lon,
        coordinate_precision=precision,
    )


def _prices(ticket: dict[str, Any]) -> tuple[str | None, str | None, str | None]:
    price = ticket.get("price") if isinstance(ticket.get("price"), dict) else None
    max_price = ticket.get("max_price") if isinstance(ticket.get("max_price"), dict) else None
    if not price:
        return None, None, None
    low = cents_to_money(price.get("min_cents")) or cents_to_money(price.get("cents"))
    high = cents_to_money((max_price or {}).get("cents")) or cents_to_money(price.get("cents"))
    currency = price.get("currency") or (max_price or {}).get("currency")
    currency = currency.upper() if isinstance(currency, str) and len(currency) == 3 else None
    if low is None and high is None:
        return None, None, None
    return low, high, currency


def normalize(record: SourceRecord, *, conference_id: str | None = None) -> Event:
    payload = record.payload
    event = payload.get("event") if isinstance(payload.get("event"), dict) else {}
    tz_name = event.get("timezone") if isinstance(event.get("timezone"), str) else None
    tz = zone(tz_name)
    start = localize(parse_instant(event.get("start_at") or payload.get("start_at")), tz)
    end = localize(parse_instant(event.get("end_at")), tz)
    if start and end and end < start:
        end = None  # contradictory source data: keep start, drop the impossible end

    hosts = [h for h in payload.get("hosts") or [] if isinstance(h, dict)]
    organizer_ids = [f"luma:host:{h['api_id']}" for h in hosts if h.get("api_id")]
    organizer_names = [str(h["name"]) for h in hosts if h.get("name")]
    calendar = payload.get("calendar") if isinstance(payload.get("calendar"), dict) else {}
    if calendar.get("api_id") and not calendar.get("is_personal"):
        organizer_ids.append(f"luma:calendar:{calendar['api_id']}")
        if calendar.get("name"):
            organizer_names.append(str(calendar["name"]))

    ticket = payload.get("ticket_info") if isinstance(payload.get("ticket_info"), dict) else {}
    price_min, price_max, currency = _prices(ticket)
    is_free = ticket.get("is_free") if isinstance(ticket.get("is_free"), bool) else None
    if ticket.get("is_sold_out") is True or payload.get("sold_out") is True:
        status = "sold_out"
    elif event.get("visibility") == "public" and start is not None:
        status = "scheduled"  # published on the public discover feed
    else:
        status = "unknown"
    guest_count = payload.get("guest_count")
    registered = guest_count if isinstance(guest_count, int) and guest_count >= 0 else None

    topics = [
        str(c.get("name")) for c in payload.get("categories") or []
        if isinstance(c, dict) and c.get("name")
    ]
    url = str(record.source_url) if record.source_url else None
    return Event(
        id=f"luma:{record.source_id}",
        conference_id=conference_id,
        title=str(event.get("name") or "").strip() or "(untitled Luma event)",
        description=payload.get("description_text") or None,
        event_type="other",
        start_at=start,
        end_at=end,
        timezone=tz_name if tz else None,
        venue=_venue(event),
        organizer_ids=organizer_ids,
        organizer_names=organizer_names,
        topics=topics,
        status=status,
        conference_relation="unknown",
        registration_url=url,
        source_url=url,
        is_free=is_free,
        price_min=price_min,
        price_max=price_max,
        currency=currency,
        capacity=None,  # spots_remaining is not capacity
        registered_count=registered,
        evidence=[
            SourceEvidence(
                provider=record.provider,
                source_mode=record.source_mode,
                source_url=url,
                collected_at=record.collected_at,
                source_record_id=record.source_id,
                raw_ref=record.content_hash,
            )
        ],
    )
