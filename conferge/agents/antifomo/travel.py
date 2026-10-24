"""Travel buffers between event venues; deterministic, no network.

Same site (official sessions of the same conference, the same site name before the
building/pavilion/room part, or coordinates within 300 m): a short room change buffer.
With exact or approximate coordinates on both venues: fixed overhead plus great-circle
distance at an urban door-to-door speed. Otherwise, two distinct sites without
coordinates: a conservative default, labelled ``unknown_default`` (``default`` in the plan).
"""

from __future__ import annotations

import math
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from conferge.agents.antifomo.models import Constraints, TravelBasis
from conferge.core.schemas import Event, Venue

_SAME_VENUE_M = 300
# Parts of a venue name that name a building, hall or room inside a site, not the site.
_SUBPLACE = re.compile(r"\b(?:building|bldg)\s+\w+\b|\b(?:center|centre|pavilion|hall|level\s+\w+|floor|room)\b")
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



def site_name(name: str | None) -> str | None:
    """'Fort Mason Building C, Founders Inc.' -> 'fort mason'; 'Room 2 @ Gateway Pavilion' -> 'gateway'."""
    if not name:
        return None
    text = name.split("@")[-1].split(",")[0].lower()
    text = " ".join(_SUBPLACE.sub(" ", text).split())
    return text or None


def _site(event: Event, c: Constraints) -> str | None:
    """The site of an event: its conference's venue for official sessions, else its site name."""
    if event.conference_relation == "official" and event.conference_id:
        return c.conference_site or f"conference:{event.conference_id}"
    return site_name(event.venue.name if event.venue else None)


def travel_minutes(a: Event, b: Event, c: Constraints) -> tuple[int, TravelBasis]:
    """Minutes needed to get from the end of ``a`` to the start of ``b``."""
    pa, pb = _coords(a.venue), _coords(b.venue)
    if pa and pb:
        dist = haversine_m(*pa, *pb)
        if dist <= _SAME_VENUE_M:
            return c.same_venue_buffer_minutes, "same_venue"
        ride = dist / 1000 / c.travel_speed_kmh * 60
        return c.travel_overhead_minutes + math.ceil(ride), "haversine"
    site_a, site_b = _site(a, c), _site(b, c)
    if site_a and site_a == site_b:
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
