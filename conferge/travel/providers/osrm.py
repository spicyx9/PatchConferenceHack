"""OSRM routing provider (public demo servers, no key).

drive: router.project-osrm.org (car profile, free-flow, no live traffic).
walk:  routing.openstreetmap.de routed-foot (foot profile).
Durations are routing estimates. Taxi/rideshare fares are never derived from them.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from conferge.core.schemas import SourceEvidence
from conferge.travel.models import Mode, Place, Price, ProviderOutcome, RouteLeg, utcnow
from conferge.travel.places import SF_TIMEZONE
from conferge.travel.providers.base import failed, report

NAME = "osrm"
DRIVE_BASE = "https://router.project-osrm.org/route/v1/driving"
WALK_BASE = "https://routing.openstreetmap.de/routed-foot/route/v1/foot"
DRIVE_WARNING = "OSRM free-flow driving time, no live traffic; taxi/rideshare fare unknown"
WALK_WARNING = "OSRM foot profile estimate"
TIMEOUT_S = 20.0


def build_url(origin: Place, destination: Place, mode: Mode) -> str:
    base = DRIVE_BASE if mode == "drive" else WALK_BASE
    coords = (
        f"{origin.longitude},{origin.latitude};{destination.longitude},{destination.latitude}"
    )
    return f"{base}/{coords}?overview=false"


class OsrmProvider:
    name = NAME
    modes: frozenset[Mode] = frozenset({"drive", "walk"})

    def __init__(self, *, client: httpx.AsyncClient | None = None) -> None:
        self._client = client

    async def _get(self, url: str) -> httpx.Response:
        if self._client is not None:
            return await self._client.get(url, timeout=TIMEOUT_S)
        async with httpx.AsyncClient(timeout=TIMEOUT_S) as client:
            return await client.get(url)

    async def route(
        self, origin: Place, destination: Place, *, mode: Mode,
        depart_at: datetime | None = None,
    ) -> ProviderOutcome:
        started = utcnow()
        if mode not in self.modes:
            return failed(NAME, started, f"osrm does not support mode {mode!r}")
        if depart_at is not None and depart_at.tzinfo is None:
            return failed(NAME, started, "depart_at must be timezone-aware")
        url = build_url(origin, destination, mode)
        try:
            response = await self._get(url)
        except httpx.HTTPError as exc:
            return failed(NAME, started, f"osrm network error: {type(exc).__name__}")
        if response.status_code == 429:
            return failed(NAME, started, "osrm HTTP 429", termination="rate_limited")
        try:
            payload: Any = response.json()
        except ValueError:
            return failed(
                NAME, started, f"osrm HTTP {response.status_code}: non-JSON body",
                termination="schema_changed" if response.status_code < 400 else "error",
            )
        code = payload.get("code") if isinstance(payload, dict) else None
        if response.status_code >= 400 or code != "Ok":
            detail = code or f"HTTP {response.status_code}"
            return failed(NAME, started, f"osrm route failed: {detail}")
        routes = payload.get("routes")
        if not isinstance(routes, list) or not routes:
            return failed(NAME, started, "osrm route failed: no routes")
        first = routes[0]
        try:
            duration_s = float(first["duration"])
            distance = float(first["distance"])
        except (KeyError, TypeError, ValueError):
            return failed(
                NAME, started, "osrm response missing duration/distance",
                termination="schema_changed",
            )
        minutes = math.ceil(duration_s / 60)
        departure = arrival = None
        if depart_at is not None:
            departure = depart_at.astimezone(ZoneInfo(SF_TIMEZONE))
            arrival = departure + timedelta(seconds=duration_s)
        if mode == "walk":
            price = Price(amount="0", currency="USD", status="exact", note="walking")
            warnings = [WALK_WARNING]
        else:
            price = Price()
            warnings = [DRIVE_WARNING]
        collected = utcnow()
        leg = RouteLeg(
            from_place=origin, to_place=destination, mode=mode,
            departure_local=departure, arrival_local=arrival,
            duration_minutes=minutes, duration_status="estimate",
            distance_m=round(distance), price=price, provider=NAME, source_mode="live",
            collected_at=collected, source_url=url, warnings=warnings,
            evidence=[SourceEvidence(
                provider=NAME, source_mode="live", source_url=url, collected_at=collected,
            )],
        )
        return ProviderOutcome(
            legs=[leg],
            run_report=report(
                NAME, started, status="ok", termination="exhausted", fetched=1, pages=1,
                warnings=warnings,
            ),
        )
