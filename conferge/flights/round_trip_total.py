"""Round-trip totals observed on the Google Flights page (Bright Data Web Unlocker).

The page lists outbound legs, each with the round-trip total. The core contract cannot hold a
round trip without its return slice and has no ``quoted_total`` flight status, so the stored
offer stays ``one_way`` with ``total_price=None`` and the total verbatim in ``raw_price_text``
("413 USD round trip total"). This module reads that total back, unchanged and never split,
and gives the display view the demo shows: a round trip, ``quoted_total``, labelled
"round trip total", ``return_slice_collected=False``.
"""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Any

from conferge.core.schemas import FlightOffer

LABEL = "round trip total"
_TEXT = re.compile(r"^\s*(\d+(?:\.\d+)?)\s+([A-Z]{3})\s+round trip total\s*$")


def round_trip_total(offer: FlightOffer) -> tuple[str, str] | None:
    """(amount, currency) as observed, or None when the offer carries no round-trip total."""
    if offer.total_price is not None or not offer.raw_price_text:
        return None
    m = _TEXT.match(offer.raw_price_text)
    return (m.group(1), m.group(2)) if m else None


def trip_price(offer: FlightOffer) -> Decimal | None:
    """What the offer costs for the trip it covers: its total, or the observed round-trip total."""
    if offer.total_price is not None:
        return Decimal(offer.total_price)
    rt = round_trip_total(offer)
    return Decimal(rt[0]) if rt else None


def is_round_trip(offer: FlightOffer) -> bool:
    return offer.trip_type == "round_trip" or round_trip_total(offer) is not None


def display(offer: FlightOffer) -> dict[str, Any]:
    """View overrides for the API; empty when the offer is shown as stored."""
    rt = round_trip_total(offer)
    if rt is None:
        return {}
    return {"trip_type": "round_trip", "price_status": "quoted_total", "total_price": rt[0],
            "currency": rt[1], "price_label": LABEL, "return_slice_collected": False}
