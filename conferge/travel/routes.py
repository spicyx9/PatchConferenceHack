"""Compose provider legs into airport -> venue and venue -> venue route options.

Deterministic: each option is a chain of provider legs; totals are only computed
when every leg is known. A missing provider produces a warning, never a guessed leg.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal

from conferge.core.schemas import RunReport
from conferge.travel.models import (
    Place,
    Price,
    ProviderOutcome,
    RouteLeg,
    RouteOption,
    RoutePlan,
)
from conferge.travel.places import EMBARCADERO
from conferge.travel.providers.base import RouteProvider

NO_511 = "Muni/Caltrain/VTA legs not computed: 511.org transit key not configured"


def combine_prices(prices: Sequence[Price]) -> Price:
    if not prices or any(p.status == "unknown" or p.amount is None for p in prices):
        return Price()
    currencies = {p.currency for p in prices}
    if len(currencies) != 1:
        return Price(note="mixed currencies, not summed")
    total = sum((Decimal(p.amount) for p in prices if p.amount), Decimal("0"))
    status = "exact" if all(p.status == "exact" for p in prices) else "estimate"
    return Price(amount=f"{total:f}", currency=currencies.pop(), status=status)


def total_minutes(legs: Sequence[RouteLeg]) -> int | None:
    if any(leg.duration_minutes is None for leg in legs):
        return None
    first, last = legs[0].departure_local, legs[-1].arrival_local
    if first and last:
        return int(-(-(last - first).total_seconds() // 60))  # ceil, like provider minutes
    return sum(leg.duration_minutes or 0 for leg in legs)


def make_option(option_id: str, label: str, legs: list[RouteLeg],
                warnings: list[str] | None = None,
                price_override: Price | None = None) -> RouteOption:
    price = price_override or combine_prices([leg.price for leg in legs])
    minutes = total_minutes(legs)
    return RouteOption(
        id=option_id, label=label, legs=legs, total_duration_minutes=minutes,
        total_price=price, complete=minutes is not None and price.status != "unknown",
        warnings=[*(warnings or []), *(w for leg in legs for w in leg.warnings)],
    )


class RoutePlanner:
    """Pluggable composition of route providers.

    bart: transit provider for BART trips; walk: routed walking (e.g. OSRM foot);
    walk_fallback: offline estimate; drive: driving time; rideshare: fare estimator.
    Any of them may be None; the plan then carries a warning instead of a leg.
    """

    def __init__(
        self, *, bart: RouteProvider | None = None, walk: RouteProvider | None = None,
        walk_fallback: RouteProvider | None = None, drive: RouteProvider | None = None,
        rideshare: RouteProvider | None = None, bart_hub: Place = EMBARCADERO,
    ) -> None:
        self.bart, self.walk, self.walk_fallback = bart, walk, walk_fallback
        self.drive, self.rideshare, self.bart_hub = drive, rideshare, bart_hub

    async def aclose(self) -> None:
        seen: set[int] = set()
        for provider in (self.bart, self.walk, self.walk_fallback, self.drive, self.rideshare):
            close = getattr(provider, "aclose", None)
            if close and id(provider) not in seen:
                seen.add(id(provider))
                await close()

    async def _walk(
        self, a: Place, b: Place, depart_at: datetime | None, reports: list[RunReport],
    ) -> RouteLeg | None:
        for provider in (self.walk, self.walk_fallback):
            if provider is None:
                continue
            outcome = await provider.route(a, b, mode="walk", depart_at=depart_at)
            reports.append(outcome.run_report)
            if outcome.legs:
                return outcome.legs[0]
        return None

    async def _drive_options(
        self, a: Place, b: Place, depart_at: datetime | None, reports: list[RunReport],
        prefix: str,
    ) -> list[RouteOption]:
        tasks: list[asyncio.Future[ProviderOutcome]] = []
        if self.drive:
            tasks.append(asyncio.ensure_future(
                self.drive.route(a, b, mode="drive", depart_at=depart_at)))
        if self.rideshare:
            tasks.append(asyncio.ensure_future(
                self.rideshare.route(a, b, mode="rideshare", depart_at=depart_at)))
        outcomes = await asyncio.gather(*tasks) if tasks else []
        for outcome in outcomes:
            reports.append(outcome.run_report)
        drive = outcomes[0].legs[0] if self.drive and outcomes[0].legs else None
        fare = None
        if self.rideshare:
            ride = outcomes[-1]
            fare = ride.legs[0].price if ride.legs else None
        if drive is None:
            return []
        if fare:
            ride_leg = outcomes[-1].legs[0]
            warnings = [f"rideshare fare from {ride_leg.provider} ({ride_leg.source_mode}, "
                        f"{ride_leg.collected_at.isoformat()}): {fare.note or fare.status}"]
        else:
            warnings = ["rideshare fare unknown: no trusted estimate collected"]
        return [make_option(f"{prefix}-drive", "Taxi or rideshare (driving time)", [drive],
                            warnings, price_override=fare)]

    async def plan(
        self, origin: Place, destination: Place, *, depart_at: datetime | None = None,
    ) -> RoutePlan:
        reports: list[RunReport] = []
        options: list[RouteOption] = []
        warnings: list[str] = []
        prefix = f"{origin.id}--{destination.id}"

        if origin.kind == "airport":
            warnings.append(NO_511)
            if origin.bart_station and self.bart:
                outcome = await self.bart.route(
                    origin, self.bart_hub, mode="bart", depart_at=depart_at)
                reports.append(outcome.run_report)
                if outcome.legs:
                    train = outcome.legs[0]
                    walk = await self._walk(
                        self.bart_hub, destination, train.arrival_local, reports)
                    legs = [train, walk] if walk else [train]
                    extra = [] if walk else ["last mile to venue not computed"]
                    options.append(make_option(
                        f"{prefix}-bart-walk", f"BART to {self.bart_hub.name} then walk",
                        legs, extra))
            elif not origin.bart_station:
                warnings.append(f"{origin.name}: no BART station; rail option not computed")
        else:
            walk = await self._walk(origin, destination, depart_at, reports)
            if walk:
                options.append(make_option(f"{prefix}-walk", "Walk", [walk]))

        options.extend(await self._drive_options(
            origin, destination, depart_at, reports, prefix))

        failures = [r for r in reports if r.status != "ok"]
        status = "failed" if not options else ("degraded" if failures else "ok")
        modes = {leg.source_mode for o in options for leg in o.legs}
        source_mode = modes.pop() if len(modes) == 1 else ("mixed" if modes else "live")
        errors = [e for r in reports for e in r.errors] + warnings
        return RoutePlan(origin=origin, destination=destination, options=options,
                         source_mode=source_mode, status=status, reports=reports,
                         errors=errors)

    async def plan_sequence(
        self, places: Sequence[Place], *, depart_at: datetime | None = None,
    ) -> list[RoutePlan]:
        """Consecutive legs between program places (hotel -> venue -> event ...)."""
        return list(await asyncio.gather(*(
            self.plan(a, b, depart_at=depart_at) for a, b in zip(places, places[1:], strict=False)
        )))


def default_planner() -> RoutePlanner:
    """Live providers with public endpoints; Uber only via Bright Data when configured."""
    from conferge.travel.providers.bart import BartProvider
    from conferge.travel.providers.osrm import OsrmProvider
    from conferge.travel.providers.uber import UberEstimateProvider
    from conferge.travel.providers.walk import HaversineWalkProvider

    osrm = OsrmProvider()
    return RoutePlanner(bart=BartProvider(), walk=osrm, walk_fallback=HaversineWalkProvider(),
                        drive=osrm, rideshare=UberEstimateProvider())
