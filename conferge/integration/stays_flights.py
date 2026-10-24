"""Live stays (w05) and flights (w06) for the demo assembly, with a visible fixture fallback.

``collect_stays_flights`` runs both live searches concurrently, each under its own
timeout. A domain that fails, times out or returns zero records is reported as such;
``assemble`` then keeps the API fixture for that domain, labelled ``fixture`` with a
warning naming the live failure. Records are never relabelled: price_status,
evidence and ``collected_at`` are those set by the provider normalizers (server
clock at collection time), money stays Decimal / decimal strings.

Flights: fast-flights only yields one-way fares (no round-trip quote), so the demo
keeps the cheapest observed outbound into SFO on the departure day and the
cheapest observed return out of SFO on the return day. Their sum is two
separate observed fares, not a quoted round trip.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from conferge.core.schemas import FlightOffer, RunStatus

DEPART, RETURN = date(2026, 10, 27), date(2026, 10, 30)
ARRIVAL_AIRPORT = "SFO"
STAY_LIMIT = 5


@dataclass
class LiveDomain:
    name: str
    """``stays`` or ``flights``."""
    items: list[Any] = field(default_factory=list)
    source_mode: str = "live"
    status: RunStatus = "failed"
    collected_at: datetime | None = None
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


async def _stays(timeout: float) -> LiveDomain:
    from conferge.lodging import run
    from conferge.lodging.models import LodgingQuery

    q = LodgingQuery(check_in=DEPART, check_out=RETURN, adults=1, currency="USD",
                     limit=STAY_LIMIT, verify_top=STAY_LIMIT,
                     conference_id="github-universe-2026")
    env = await asyncio.wait_for(run(q), timeout=timeout)
    providers = [f"{r.provider}: {r.status}" for r in env.reports]
    return LiveDomain("stays", list(env.items)[:STAY_LIMIT], env.source_mode, env.status,
                      env.collected_at, providers, list(env.errors))


def _departs(offer: FlightOffer) -> date | None:
    seg = offer.slices[0].segments[0] if offer.slices and offer.slices[0].segments else None
    return seg.departure_at.date() if seg and seg.departure_at else None


def pick_flights(offers: list[FlightOffer]) -> list[FlightOffer]:
    """Cheapest priced round trip, else cheapest outbound into SFO + cheapest return from SFO."""
    priced = sorted((o for o in offers if o.total_price is not None),
                    key=lambda o: (Decimal(o.total_price), o.id))  # type: ignore[arg-type]
    round_trip = next((o for o in priced if o.trip_type == "round_trip"), None)
    if round_trip:
        return [round_trip]
    out = next((o for o in priced if o.trip_type == "one_way" and _departs(o) == DEPART
                and o.slices[0].segments[-1].destination_iata == ARRIVAL_AIRPORT), None)
    back = next((o for o in priced if o.trip_type == "one_way" and _departs(o) == RETURN
                 and o.slices[0].segments[0].origin_iata == ARRIVAL_AIRPORT), None)
    return [o for o in (out, back) if o is not None]


async def _flights(timeout: float) -> LiveDomain:
    from conferge.flights import run

    env = await asyncio.wait_for(run({
        "origin_city": "New York", "destination_city": "San Francisco",
        "departure_date": DEPART.isoformat(), "return_date": RETURN.isoformat(),
    }), timeout=timeout)
    picked = pick_flights(list(env.items))
    warnings = [f"{len(env.items)} offers collected, {len(picked)} kept for the itinerary"]
    if picked and all(o.trip_type == "one_way" for o in picked):
        warnings.append("trip total is two separately observed one-way fares, not a round-trip quote")
    errors = list(env.errors)
    if env.items and not picked:
        errors.append(f"no priced offer into {ARRIVAL_AIRPORT} on {DEPART} / back on {RETURN}")
    return LiveDomain("flights", picked, env.source_mode, env.status, env.collected_at,
                      warnings, errors)


async def _guarded(name: str, coro: Any) -> LiveDomain:
    try:
        return await coro
    except Exception as exc:  # noqa: BLE001 - timeout or provider bug is a visible failure
        kind = "timeout" if isinstance(exc, (asyncio.TimeoutError, TimeoutError)) else "error"
        return LiveDomain(name, collected_at=datetime.now(timezone.utc),
                          errors=[f"{kind}: {type(exc).__name__}: {str(exc)[:200]}"])


async def collect_stays_flights(timeout: float = 90.0) -> dict[str, LiveDomain]:
    stays, flights = await asyncio.gather(_guarded("stays", _stays(timeout)),
                                          _guarded("flights", _flights(timeout)))
    return {"stays": stays, "flights": flights}


def usable(domain: LiveDomain | None) -> bool:
    """Live records that may replace the fixture: non-empty, not failed, not fixture."""
    return bool(domain and domain.items and domain.status != "failed"
                and domain.source_mode in {"live", "cached", "mixed"})


__all__ = ["LiveDomain", "collect_stays_flights", "pick_flights", "usable"]
