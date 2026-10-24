"""Travel buffers between event venues; deterministic, no network.

With exact or approximate coordinates on both venues: fixed overhead plus
great-circle distance at an urban door-to-door speed. Same venue: a short room
change buffer. Otherwise a conservative default, labelled ``unknown_default``.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from conferge.agents.antifomo.models import Constraints, TravelBasis
from conferge.core.schemas import Event, Venue

_SAME_VENUE_M = 150
_USABLE_PRECISION = {"exact", "approximate"}


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6_371_000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _coords(venue: Venue | None) -> tuple[float, float] | None:
    if venue is None or venue.latitude is None or venue.longitude is None:
        return None
    if venue.coordinate_precision not in _USABLE_PRECISION:
        return None
    return venue.latitude, venue.longitude


def _norm(name: str | None) -> str | None:
    return " ".join(name.lower().split()) if name else None


def travel_minutes(a: Event, b: Event, c: Constraints) -> tuple[int, TravelBasis]:
    """Minutes needed to get from the end of ``a`` to the start of ``b``."""
    va, vb = a.venue, b.venue
    name_a, name_b = _norm(va.name if va else None), _norm(vb.name if vb else None)
    pa, pb = _coords(va), _coords(vb)
    if pa and pb:
        dist = haversine_m(*pa, *pb)
        if dist <= _SAME_VENUE_M:
            return c.same_venue_buffer_minutes, "same_venue"
        ride = dist / 1000 / c.travel_speed_kmh * 60
        return c.travel_overhead_minutes + math.ceil(ride), "haversine"
    if name_a and name_a == name_b:
        return c.same_venue_buffer_minutes, "same_venue"
    return c.default_travel_minutes, "unknown_default"


def fits_before(a: Event, b: Event, c: Constraints) -> bool:
    """True when ``b`` can follow ``a`` including the travel buffer."""
    assert a.end_at and b.start_at
    minutes, _ = travel_minutes(a, b, c)
    return a.end_at + timedelta(minutes=minutes) <= b.start_at


def compatible(a: Event, b: Event, c: Constraints) -> bool:
    return fits_before(a, b, c) or fits_before(b, a, c)


def local_day(dt: datetime, tz: str) -> str:
    return dt.astimezone(ZoneInfo(tz)).date().isoformat()
