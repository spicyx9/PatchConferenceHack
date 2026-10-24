"""Partiful `SourceRecord` -> `conferge.core.schemas.Event` (facts only, rest None)."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from conferge.core.schemas import Event, SourceEvidence, SourceRecord, Venue
from conferge.events.luma._util import localize, parse_instant, zone

_STATUS = {"PUBLISHED": "scheduled", "CANCELED": "cancelled", "CANCELLED": "cancelled"}


def _venue(event: dict[str, Any], place: Any) -> Venue | None:
    info = event.get("locationInfo") if isinstance(event.get("locationInfo"), dict) else None
    if not info:
        return None
    maps = info.get("mapsInfo") if isinstance(info.get("mapsInfo"), dict) else {}
    lines = maps.get("addressLines") or info.get("displayAddressLines") or []
    lines = [str(x) for x in lines if x]
    city = None
    if isinstance(place, dict) and isinstance(place.get("address"), dict):
        city = place["address"].get("addressLocality")
    approx = maps.get("approximateLocation")
    if not city and isinstance(approx, str) and approx:
        city = approx.split(",")[0].strip() or None
    address = ", ".join(lines) if maps.get("addressLines") else None
    if not address and not city:
        return None
    return Venue(
        name=lines[0] if address and lines else None,
        address=address,
        city=city,
        coordinate_precision="unknown",  # no coordinates in Partiful payloads
    )


def _prices(offers: Any) -> tuple[bool | None, str | None, str | None, str | None]:
    if not isinstance(offers, list) or not offers:
        return None, None, None, None
    values: list[Decimal] = []
    currencies = set()
    for offer in offers:
        if not isinstance(offer, dict):
            continue
        try:
            values.append(Decimal(str(offer.get("price"))))
        except (InvalidOperation, ValueError):
            continue
        if isinstance(offer.get("priceCurrency"), str):
            currencies.add(offer["priceCurrency"].upper())
    values = [v for v in values if v.is_finite() and v >= 0]
    if not values:
        return None, None, None, None
    currency = currencies.pop() if len(currencies) == 1 else None
    if currency is None:
        return None, None, None, None  # ambiguous currency: do not guess
    q = Decimal("0.01")
    return (
        max(values) == 0, str(min(values).quantize(q)), str(max(values).quantize(q)), currency
    )


def normalize(record: SourceRecord, *, conference_id: str | None = None) -> Event:
    payload = record.payload
    event = payload.get("event") if isinstance(payload.get("event"), dict) else {}
    tz_name = event.get("timezone") if isinstance(event.get("timezone"), str) else None
    tz = zone(tz_name)
    start = localize(parse_instant(event.get("startDate")), tz)
    end = localize(parse_instant(event.get("endDate")), tz)
    if start and end and end < start:
        end = None

    owner_ids = [f"partiful:user:{o}" for o in event.get("ownerIds") or [] if isinstance(o, str)]
    names = [str(h["name"]) for h in payload.get("hosts") or [] if isinstance(h, dict) and h.get("name")]
    if not names and isinstance(event.get("hostName"), str) and event["hostName"]:
        names = [event["hostName"]]
    is_free, price_min, price_max, currency = _prices(payload.get("offers"))
    going = event.get("goingGuestCount")
    registered = going if event.get("showGuestCount") and isinstance(going, int) and going >= 0 else None
    status = _STATUS.get(str(event.get("status") or "").upper(), "unknown")
    if status == "scheduled" and event.get("atCapacity") is True:
        status = "sold_out"
    url = str(record.source_url) if record.source_url else None
    description = event.get("description")
    return Event(
        id=f"partiful:{record.source_id}",
        conference_id=conference_id,
        title=str(event.get("title") or "").strip() or "(untitled Partiful event)",
        description=description.strip() if isinstance(description, str) and description.strip() else None,
        event_type="other",
        start_at=start,
        end_at=end,
        timezone=tz_name if tz else None,
        venue=_venue(event, payload.get("place")),
        organizer_ids=owner_ids,
        organizer_names=names,
        status=status,
        conference_relation="unknown",
        registration_url=url,
        source_url=url,
        is_free=is_free,
        price_min=price_min,
        price_max=price_max,
        currency=currency,
        registered_count=registered,
        evidence=[
            SourceEvidence(
                provider=record.provider, source_mode=record.source_mode, source_url=url,
                collected_at=record.collected_at, source_record_id=record.source_id,
                raw_ref=record.content_hash,
            )
        ],
    )
