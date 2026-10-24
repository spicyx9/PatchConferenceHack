"""schema.org Event JSON-LD extraction and normalization for independent pages.

Only values present in the page are kept: naive datetimes, unknown prices and
unknown venues stay None. The resulting Event is never linked to a conference here.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from html.parser import HTMLParser
from typing import Any

from pydantic import ValidationError

from conferge.core.schemas import Event, SourceEvidence, SourceRecord, Venue

_PRICE_RE = re.compile(r"^[0-9]+(?:\.[0-9]{1,4})?$")
_STATUS = {
    "eventcancelled": "cancelled",
    "eventpostponed": "postponed",
    "eventrescheduled": "scheduled",
    "eventscheduled": "scheduled",
    "eventmovedonline": "scheduled",
}


class _LdParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[str] = []
        self._buf: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "script" and any(
            k == "type" and (v or "").strip().lower() == "application/ld+json" for k, v in attrs
        ):
            self._buf = []

    def handle_data(self, data: str) -> None:
        if self._buf is not None:
            self._buf.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self._buf is not None:
            self.blocks.append("".join(self._buf))
            self._buf = None


def _walk(node: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if isinstance(node, list):
        for item in node:
            out.extend(_walk(item))
    elif isinstance(node, dict):
        out.append(node)
        if "@graph" in node:
            out.extend(_walk(node["@graph"]))
    return out


def is_event_type(block: dict[str, Any]) -> bool:
    kinds = block.get("@type")
    kinds = kinds if isinstance(kinds, list) else [kinds]
    return any(isinstance(k, str) and k.endswith("Event") for k in kinds)


def extract_event_jsonld(html: str) -> list[dict[str, Any]]:
    """All schema.org `*Event` objects found in ld+json script blocks."""
    parser = _LdParser()
    try:
        parser.feed(html)
    except Exception:  # noqa: BLE001 - malformed HTML must not crash discovery
        return []
    events: list[dict[str, Any]] = []
    for raw in parser.blocks:
        try:
            data = json.loads(raw.strip())
        except ValueError:
            continue
        events.extend(b for b in _walk(data) if is_event_type(b))
    return events


def _aware(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _text(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _float(value: Any) -> float | None:
    try:
        return float(value) if value is not None and value != "" else None
    except (TypeError, ValueError):
        return None


def _venue(location: Any) -> Venue | None:
    if isinstance(location, list):
        location = next((x for x in location if isinstance(x, dict)), None)
    if not isinstance(location, dict):
        return Venue(name=_text(location)) if _text(location) else None
    if "VirtualLocation" in str(location.get("@type")):
        return None
    address = location.get("address")
    city = None
    if isinstance(address, dict):
        city = _text(address.get("addressLocality"))
        parts = [address.get(k) for k in ("streetAddress", "addressLocality", "addressRegion",
                                          "postalCode")]
        address_text = ", ".join(p.strip() for p in parts if isinstance(p, str) and p.strip())
    else:
        address_text = _text(address)
    geo = location.get("geo") if isinstance(location.get("geo"), dict) else {}
    lat, lng = _float(geo.get("latitude")), _float(geo.get("longitude"))
    if lat is not None and not -90 <= lat <= 90:
        lat = None
    if lng is not None and not -180 <= lng <= 180:
        lng = None
    venue = Venue(
        name=_text(location.get("name")), address=address_text or None, city=city,
        latitude=lat, longitude=lng,
        coordinate_precision="exact" if lat is not None and lng is not None else "unknown",
    )
    return venue if any([venue.name, venue.address, venue.city, lat]) else None


def _names(value: Any) -> list[str]:
    items = value if isinstance(value, list) else [value]
    names: list[str] = []
    for item in items:
        name = _text(item.get("name")) if isinstance(item, dict) else _text(item)
        if name and name not in names:
            names.append(name)
    return names


def _prices(offers: Any) -> tuple[str | None, str | None, str | None]:
    items = offers if isinstance(offers, list) else [offers]
    values: list[str] = []
    currency: str | None = None
    for offer in items:
        if not isinstance(offer, dict):
            continue
        for key in ("price", "lowPrice", "highPrice"):
            raw = offer.get(key)
            text = str(raw).strip() if raw is not None else ""
            if _PRICE_RE.match(text):
                values.append(text)
        cur = offer.get("priceCurrency")
        if isinstance(cur, str) and re.fullmatch(r"[A-Z]{3}", cur.strip()):
            currency = cur.strip()
    if not values or currency is None:
        return None, None, None
    ordered = sorted(values, key=float)
    return ordered[0], ordered[-1], currency


def _url(value: Any) -> str | None:
    text = _text(value)
    return text if text and text.startswith(("http://", "https://")) else None


def event_id_for(provider: str, source_id: str) -> str:
    return f"evt:{provider}:{source_id}"


def normalize_jsonld(
    block: dict[str, Any], record: SourceRecord, *, conference_id: str | None = None,
) -> Event:
    """Map one schema.org Event object to `Event`; unknown stays None."""
    start, end = _aware(block.get("startDate")), _aware(block.get("endDate"))
    if start and end and end < start:
        end = None
    price_min, price_max, currency = _prices(block.get("offers"))
    free = block.get("isAccessibleForFree")
    is_free = free if isinstance(free, bool) else None
    if is_free is None and price_max is not None and float(price_max) == 0:
        is_free = True
    status_raw = str(block.get("eventStatus") or "").rsplit("/", 1)[-1].casefold()
    title = _text(block.get("name")) or "(untitled event)"
    lowered = title.casefold()
    event_type = "other"
    if any(w in lowered for w in ("party", "happy hour", "mixer")):
        event_type = "party"
    elif "meetup" in lowered:
        event_type = "meetup"
    elif "workshop" in lowered:
        event_type = "workshop"
    source_url = record.source_url
    evidence = SourceEvidence(
        provider=record.provider, source_mode=record.source_mode, source_url=source_url,
        collected_at=record.collected_at, source_record_id=record.source_id,
        raw_ref=record.request_id,
    )
    fields: dict[str, Any] = {
        "id": event_id_for(record.provider, record.source_id),
        "conference_id": conference_id,
        "title": title,
        "description": _text(block.get("description")),
        "event_type": event_type,
        "start_at": start,
        "end_at": end,
        "venue": _venue(block.get("location")),
        "organizer_names": _names(block.get("organizer")),
        "status": _STATUS.get(status_raw, "unknown"),
        "source_url": source_url,
        "is_free": is_free,
        "price_min": price_min,
        "price_max": price_max,
        "currency": currency,
        "evidence": [evidence],
    }
    offers = block.get("offers")
    first_offer = offers[0] if isinstance(offers, list) and offers else offers
    reg = _url(first_offer.get("url")) if isinstance(first_offer, dict) else None
    try:
        return Event(**fields, registration_url=reg)
    except ValidationError:
        return Event(**fields)


def payload_hash(payload: dict[str, Any]) -> str:
    blob = json.dumps(payload, sort_keys=True, default=str).encode()
    return hashlib.sha256(blob).hexdigest()
