"""Offline deterministic walking estimate (haversine x detour factor).

Not a routed path. Used only as a labelled fallback when no routing service answers.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from conferge.core.schemas import SourceEvidence
from conferge.travel.models import Mode, Place, Price, ProviderOutcome, RouteLeg, utcnow
from conferge.travel.places import SF_TIMEZONE
from conferge.travel.providers.base import failed, report

NAME = "haversine"
EARTH_RADIUS_M = 6_371_008.8


def haversine_m(a: Place, b: Place) -> float:
    """Great-circle distance in meters between two places."""
    lat1, lat2 = math.radians(a.latitude), math.radians(b.latitude)
    dlat = lat2 - lat1
    dlon = math.radians(b.longitude - a.longitude)
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(h)))


class HaversineWalkProvider:
    name = NAME
    modes: frozenset[Mode] = frozenset({"walk"})

    def __init__(self, speed_kmh: float = 5.0, detour_factor: float = 1.3) -> None:
        if speed_kmh <= 0 or detour_factor < 1:
            raise ValueError("speed_kmh must be > 0 and detour_factor >= 1")
        self.speed_kmh = speed_kmh
        self.detour_factor = detour_factor

    @property
    def warning(self) -> str:
        return (
            f"straight-line estimate x{self.detour_factor:g} detour at "
            f"{self.speed_kmh:g} km/h, not a routed path"
        )

    async def route(
        self, origin: Place, destination: Place, *, mode: Mode,
        depart_at: datetime | None = None,
    ) -> ProviderOutcome:
        started = utcnow()
        if mode not in self.modes:
            return failed(NAME, started, f"haversine does not support mode {mode!r}")
        if depart_at is not None and depart_at.tzinfo is None:
            return failed(NAME, started, "depart_at must be timezone-aware")
        distance_m = haversine_m(origin, destination) * self.detour_factor
        minutes = math.ceil(distance_m / 1000 / self.speed_kmh * 60)
        departure = arrival = None
        if depart_at is not None:
            departure = depart_at.astimezone(ZoneInfo(SF_TIMEZONE))
            arrival = departure + timedelta(minutes=minutes)
        collected = utcnow()
        warnings = [self.warning]
        leg = RouteLeg(
            from_place=origin, to_place=destination, mode="walk",
            departure_local=departure, arrival_local=arrival,
            duration_minutes=minutes, duration_status="estimate",
            distance_m=round(distance_m),
            price=Price(amount="0", currency="USD", status="exact", note="walking"),
            provider=NAME, source_mode="live", collected_at=collected, warnings=warnings,
            evidence=[SourceEvidence(provider=NAME, source_mode="live", collected_at=collected)],
        )
        return ProviderOutcome(
            legs=[leg],
            run_report=report(
                NAME, started, status="ok", termination="not_applicable", fetched=1,
                warnings=warnings,
            ),
        )
