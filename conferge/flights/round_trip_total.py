"""Round-trip totals observed on the Google Flights page (Bright Data Web Unlocker).

The page lists outbound legs, each with the round-trip total. The offer is stored as what the
page shows: ``trip_type round_trip``, ``total_price`` the observed total (never split),
``price_status quoted_total``, ``return_slice_collected False`` (the return slice is not on the
page) and the text verbatim in ``raw_price_text`` ("413 USD round trip total"). FalkorDB, the
API and the screen read the same fields; ``display`` only adds a label, it rewrites nothing.

``as_stored`` upgrades an offer saved before this contract (``one_way``, ``total_price None``,
the total only in ``raw_price_text``) to that form, from its own text, without a new collection.
"""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Any

from conferge.core.schemas import FlightOffer

LABEL = "round trip total"
_TEXT = re.compile(r"^\s*(\d+(?:\.\d+)?)\s+([A-Z]{3})\s+round trip total\s*$")
WARNING = ("round_trip_total_quoted: the page shows the round-trip total; "
           "the return slice was not collected")


def round_trip_total(offer: FlightOffer) -> tuple[str, str] | None:
    """(amount, currency) read from ``raw_price_text``, or None."""
    m = _TEXT.match(offer.raw_price_text or "")
    return (m.group(1), m.group(2)) if m else None


def as_stored(offer: FlightOffer) -> FlightOffer:
    """An offer whose raw text is a round-trip total, in the stored round-trip form."""
    rt = round_trip_total(offer)
    if rt is None or (offer.trip_type == "round_trip" and offer.price_status == "quoted_total"):
        return offer
    warnings = [w for w in offer.warnings if not w.startswith("round_trip_total_not_split")]
    return FlightOffer.model_validate({
        **offer.model_dump(), "trip_type": "round_trip", "total_price": rt[0], "currency": rt[1],
        "price_status": "quoted_total", "return_slice_collected": False,
        "warnings": list(dict.fromkeys([*warnings, WARNING])),
    })


def trip_price(offer: FlightOffer) -> Decimal | None:
    """What the offer costs for the trip it covers: its stored total."""
    return Decimal(offer.total_price) if offer.total_price is not None else None


def is_round_trip(offer: FlightOffer) -> bool:
    return offer.trip_type == "round_trip"


def display(offer: FlightOffer) -> dict[str, Any]:
    """A label for the API, read from the stored fields; never overrides them."""
    if offer.trip_type == "round_trip" and offer.return_slice_collected is False:
        return {"price_label": LABEL}
    return {}
