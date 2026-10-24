"""Itinerary identity and offer grouping.

itinerary_id = hash of the physical segments (carrier + flight number +
departure UTC + arrival UTC). Price is never part of identity: the same
physical flights seen at two sources are one itinerary with several offers.
A segment missing a flight number or a time cannot be identified safely, so
the itinerary key then includes a uniqueness salt and is never merged.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from collections.abc import Iterable, Sequence
from datetime import timezone
from decimal import Decimal

from conferge.core.schemas import FlightOffer, FlightSlice

UNMERGEABLE_PREFIX = "itin-unk-"


def _segment_key(segment) -> str | None:
    if not (segment.flight_number and segment.departure_at and segment.arrival_at):
        return None
    carrier = (segment.marketing_carrier or "").strip().upper()
    number = segment.flight_number.replace(" ", "").upper()
    dep = segment.departure_at.astimezone(timezone.utc).strftime("%Y%m%dT%H%M")
    arr = segment.arrival_at.astimezone(timezone.utc).strftime("%Y%m%dT%H%M")
    return f"{carrier}|{number}|{segment.origin_iata}|{dep}|{segment.destination_iata}|{arr}"


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def itinerary_id(slices: Sequence[FlightSlice]) -> str:
    keys: list[str] = []
    for index, flight_slice in enumerate(slices):
        for segment in flight_slice.segments:
            key = _segment_key(segment)
            if key is None:
                # Not safely identifiable: deterministic but marked unmergeable.
                loose = f"{segment.origin_iata}-{segment.destination_iata}-{segment.departure_at}"
                return UNMERGEABLE_PREFIX + _digest(f"{index}|{loose}|{len(keys)}|{keys}")
            keys.append(f"{index}:{key}")
    return "itin-" + _digest("/".join(keys))


def offer_id(
    itin: str, provider: str, fare: str | None,
    carry_on: bool | None, checked: int | None,
) -> str:
    return "fo-" + _digest(f"{itin}|{provider}|{fare}|{carry_on}|{checked}")


def is_mergeable(offer: FlightOffer) -> bool:
    return bool(offer.dedup_key) and not offer.dedup_key.startswith(UNMERGEABLE_PREFIX)


def group_by_itinerary(offers: Iterable[FlightOffer]) -> dict[str, list[FlightOffer]]:
    """Group offers by physical itinerary; unidentifiable offers stay alone."""
    groups: dict[str, list[FlightOffer]] = defaultdict(list)
    for offer in offers:
        key = offer.dedup_key if is_mergeable(offer) else f"{offer.dedup_key}|{offer.id}"
        groups[key].append(offer)
    return dict(groups)


def dedupe_offers(offers: Iterable[FlightOffer]) -> list[FlightOffer]:
    """Drop exact duplicate offers (same offer id), keep one per id.

    Several offers for one itinerary (different providers or fares) are all
    kept; use `group_by_itinerary` to display them together.
    """
    seen: dict[str, FlightOffer] = {}
    for offer in offers:
        current = seen.get(offer.id)
        if current is None or offer.collected_at > current.collected_at:
            seen[offer.id] = offer
    return list(seen.values())


def cheapest(offers: Iterable[FlightOffer], currency: str = "USD") -> FlightOffer | None:
    priced = [o for o in offers if o.total_price is not None and o.currency == currency]
    return min(priced, key=lambda o: Decimal(o.total_price)) if priced else None
