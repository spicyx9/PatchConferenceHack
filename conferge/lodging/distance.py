"""Straight-line distance and walking-time estimate from a stay to venues.

Haversine on WGS84 mean radius; walking minutes assume 5 km/h on the straight line, so
they are a lower bound (labelled ``estimate`` by callers). Unknown coordinates -> None.
"""

from __future__ import annotations

import math
from typing import Any

from conferge.core.schemas import Lodging
from conferge.lodging.models import Place

EARTH_RADIUS_M = 6_371_008.8
WALK_KMH = 5.0


def haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(a)))


def walk_minutes(meters: float | None) -> int | None:
    if meters is None:
        return None
    return math.ceil(meters / (WALK_KMH * 1000 / 60))


def _coords(lodging: Lodging) -> tuple[float, float] | None:
    v = lodging.venue
    if v is None or v.latitude is None or v.longitude is None:
        return None
    return v.latitude, v.longitude


def distance_to(lodging: Lodging, place: Place) -> int | None:
    coords = _coords(lodging)
    if coords is None:
        return None
    return round(haversine_m(coords[0], coords[1], place.lat, place.lng))


def with_venue_distance(lodging: Lodging, venue: Place) -> Lodging:
    return lodging.model_copy(update={"distance_to_venue_m": distance_to(lodging, venue)})


def distances(lodging: Lodging, places: list[Place]) -> list[dict[str, Any]]:
    """Distance and walk estimate to every place of the plan (venue first if included)."""
    precision = lodging.venue.coordinate_precision if lodging.venue else "unknown"
    out = []
    for place in places:
        meters = distance_to(lodging, place)
        out.append({
            "place_id": place.id, "place_name": place.name, "distance_m": meters,
            "walk_minutes_estimate": walk_minutes(meters), "method": "haversine_walk_5kmh",
            "coordinate_precision": precision,
        })
    return out
