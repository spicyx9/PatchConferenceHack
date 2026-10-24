"""Straight-line travel estimates between venues.

These are *estimates*, labelled as such in every output: haversine distance at
an assumed urban door-to-door speed. Missing coordinates give ``None``; the
caller then applies a visible conservative buffer instead of guessing a time.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from conferge.core.schemas import Venue

URBAN_SPEED_KMH = 15.0      # walk + transit/rideshare mix in San Francisco
SAME_VENUE_MIN = 5          # moving between rooms of one venue
UNKNOWN_BUFFER_MIN = 30     # used when a venue has no coordinates
METHOD = f"estimate: straight line at {URBAN_SPEED_KMH:g} km/h"


@dataclass(frozen=True)
class TravelEstimate:
    minutes: int
    distance_m: int | None
    method: str

    def as_dict(self) -> dict[str, object]:
        return {"minutes": self.minutes, "distance_m": self.distance_m, "method": self.method}


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> int:
    r = 6_371_000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return int(round(2 * r * math.asin(math.sqrt(a))))


def _coords(venue: Venue | None) -> tuple[float, float] | None:
    if venue is None or venue.latitude is None or venue.longitude is None:
        return None
    return venue.latitude, venue.longitude


def estimate(a: Venue | None, b: Venue | None) -> TravelEstimate:
    if a is not None and b is not None and a.name and a.name == b.name:
        return TravelEstimate(SAME_VENUE_MIN, 0, "same venue")
    ca, cb = _coords(a), _coords(b)
    if ca is None or cb is None:
        return TravelEstimate(UNKNOWN_BUFFER_MIN, None,
                              f"unknown: venue coordinates missing, {UNKNOWN_BUFFER_MIN} min buffer")
    distance = haversine_m(*ca, *cb)
    if distance < 150:
        return TravelEstimate(SAME_VENUE_MIN, distance, METHOD)
    minutes = math.ceil(distance / 1000 / URBAN_SPEED_KMH * 60) + SAME_VENUE_MIN
    return TravelEstimate(minutes, distance, METHOD)
