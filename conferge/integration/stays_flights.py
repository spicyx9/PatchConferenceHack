"""Live stays (w05) and flights (w06) for the demo assembly, with a visible fixture fallback.

``collect_stays_flights`` runs both live searches concurrently, each under its own
timeout. A domain that fails, times out or returns zero records is reported as such;
``assemble`` then keeps the API fixture for that domain, labelled ``fixture`` with a
warning naming the live failure. Records are never relabelled: price_status,
evidence and ``collected_at`` are those set by the provider normalizers (server
clock at collection time), money stays Decimal / decimal strings.

Provenance: every stay and flight is ranked by ``conferge.api.provenance.source_of`` tier
(0 Bright Data dataset, 1 Bright Data Web Unlocker, 2 fallback library, 3 fixture/unknown).
Duplicates across providers collapse onto the lowest tier; the stays list is ordered by tier
then by the service order, and the flights are picked from the best tier that can supply a
whole trip. Counts per source label are added to the domain warnings.

Flights: fast-flights only yields one-way fares (no round-trip quote), so the demo
keeps the cheapest observed outbound into SFO on the departure day and the
cheapest observed return out of SFO on the return day. Their sum is two
separate observed fares, not a quoted round trip.
"""

from __future__ import annotations

import asyncio
import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from conferge.api.provenance import source_of
from conferge.core.schemas import FlightOffer, Lodging, RunReport, RunStatus
from conferge.flights.round_trip_total import is_round_trip, trip_price
from conferge.lodging.dedupe import normalize_name

DEPART, RETURN = date(2026, 10, 27), date(2026, 10, 30)
ARRIVAL_AIRPORT = "SFO"
STAY_LIMIT = 6
ADULTS = 2


def _tier(item: Any) -> int:
    return int(source_of(item.evidence)["tier"])


def source_counts(items: Iterable[Any]) -> str:
    """``"Bright Data dataset gd_... (Booking) x3, Fallback pyairbnb x2"`` (most common first)."""
    counts = Counter(source_of(i.evidence)["label"] for i in items)
    return ", ".join(f"{label} x{n}" for label, n in counts.most_common()) or "none"


def _norm_text(text: str | None) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).split())


def _same_stay(a: Lodging, b: Lodging) -> bool:
    name_a, name_b = normalize_name(a.name), normalize_name(b.name)
    if not name_a or name_a != name_b:
        return False
    addr_a = _norm_text(a.venue.address if a.venue else None)
    addr_b = _norm_text(b.venue.address if b.venue else None)
    if addr_a and addr_b:
        return addr_a == addr_b
    # One side has no address: the same name in the same city is the same stay. A missing
    # city counts as the query city (every demo search targets San Francisco).
    city_a = _norm_text(a.venue.city if a.venue else None)
    city_b = _norm_text(b.venue.city if b.venue else None)
    return not city_a or not city_b or city_a == city_b


def pick_stays(stays: Iterable[Lodging], limit: int = STAY_LIMIT) -> list[Lodging]:
    """Order by source tier (stable on the service order), drop cross-provider duplicates
    keeping the lowest tier, keep ``limit``."""
    kept: list[Lodging] = []
    for stay in sorted(stays, key=_tier):
        if not any(_same_stay(stay, k) for k in kept):
            kept.append(stay)
    return kept[:limit]


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
    reports: list[RunReport] = field(default_factory=list)
    """Provider RunReports, kept for the data pipeline panel."""


async def _stays(timeout: float) -> LiveDomain:
    from conferge.lodging import run
    from conferge.lodging.models import LodgingQuery

    q = LodgingQuery(check_in=DEPART, check_out=RETURN, adults=ADULTS, currency="USD",
                     limit=STAY_LIMIT, verify_top=STAY_LIMIT,
                     conference_id="github-universe-2026")
    env = await asyncio.wait_for(run(q), timeout=timeout)
    stays = pick_stays(env.items)
    warnings = [f"{r.provider}: {r.status}" for r in env.reports]
    warnings.append(f"stays sources: {source_counts(stays)}")
    return LiveDomain("stays", stays, env.source_mode, env.status,
                      env.collected_at, warnings, list(env.errors), list(env.reports))


def _departs(offer: FlightOffer) -> date | None:
    seg = offer.slices[0].segments[0] if offer.slices and offer.slices[0].segments else None
    return seg.departure_at.date() if seg and seg.departure_at else None


def flight_key(offer: FlightOffer) -> tuple[Any, ...]:
    """Same flight across providers: all segment flight numbers + first departure; without
    flight numbers (fast-flights), marketing carriers + origin + first departure; with
    neither, the offer is only equal to itself."""
    segments = [seg for sl in offer.slices for seg in sl.segments]
    first = segments[0]
    dep = first.departure_at.isoformat() if first.departure_at else None
    numbers = [_norm_text(seg.flight_number).replace(" ", "") for seg in segments]
    if all(numbers):
        return ("numbers", tuple(numbers), dep)
    carriers = tuple(_norm_text(seg.marketing_carrier) for seg in segments)
    if not all(carriers) or dep is None:
        return ("offer", offer.id)  # too little identity to call two offers the same flight
    return ("carriers", carriers, first.origin_iata, dep)


def dedupe_flights(offers: Iterable[FlightOffer]) -> list[FlightOffer]:
    """One offer per ``flight_key``, the lowest tier (then cheapest) winning."""
    def rank(o: FlightOffer) -> tuple[Any, ...]:
        price = trip_price(o)
        price = price if price is not None else Decimal("Infinity")
        return (_tier(o), price, o.id)

    best: dict[tuple[Any, ...], FlightOffer] = {}
    for offer in sorted(offers, key=rank):
        best.setdefault(flight_key(offer), offer)
    return list(best.values())


def _trip(priced: list[FlightOffer]) -> tuple[FlightOffer | None, FlightOffer | None,
                                              FlightOffer | None]:
    round_trip = next((o for o in priced if is_round_trip(o)), None)
    out = next((o for o in priced if o.trip_type == "one_way" and _departs(o) == DEPART
                and o.slices[0].segments[-1].destination_iata == ARRIVAL_AIRPORT), None)
    back = next((o for o in priced if o.trip_type == "one_way" and _departs(o) == RETURN
                 and o.slices[0].segments[0].origin_iata == ARRIVAL_AIRPORT), None)
    return round_trip, out, back


def pick_flights(offers: list[FlightOffer]) -> list[FlightOffer]:
    """Within the best source tier able to supply a whole trip: the cheapest priced round
    trip, else the cheapest outbound into SFO + cheapest return from SFO. If no single tier
    covers the trip, each leg comes from the best tier that has it."""
    # A round-trip total observed on the Google Flights page (Web Unlocker) counts as a
    # priced round trip: the total as shown, never split (see flights.round_trip_total).
    priced = sorted((o for o in dedupe_flights(offers) if trip_price(o) is not None),
                    key=lambda o: (trip_price(o), o.id))
    for tier in sorted({_tier(o) for o in priced}):
        round_trip, out, back = _trip([o for o in priced if _tier(o) == tier])
        if round_trip:
            return [round_trip]
        if out and back:
            return [out, back]
    by_tier = sorted(priced, key=_tier)  # stable: cheapest first within a tier
    _, out, back = _trip(by_tier)
    return [o for o in (out, back) if o is not None]


async def _flights(timeout: float) -> LiveDomain:
    from conferge.flights import run

    env = await asyncio.wait_for(run({
        "origin_city": "New York", "destination_city": "San Francisco",
        "departure_date": DEPART.isoformat(), "return_date": RETURN.isoformat(),
    }), timeout=timeout)
    picked = pick_flights(list(env.items))
    warnings = [f"{len(env.items)} offers collected, {len(picked)} kept for the itinerary",
                f"flights sources collected: {source_counts(env.items)}",
                f"flights sources kept: {source_counts(picked)}"]
    if any(o.raw_price_text and o.total_price is None for o in picked):
        warnings.append("round trip total observed on the Google Flights page (Bright Data "
                        "Web Unlocker), shown as is; the return slice was not collected")
    elif picked and all(o.trip_type == "one_way" for o in picked):
        warnings.append("trip total is two separately observed one-way fares, not a round-trip quote")
    errors = list(env.errors)
    if env.items and not picked:
        errors.append(f"no priced offer into {ARRIVAL_AIRPORT} on {DEPART} / back on {RETURN}")
    return LiveDomain("flights", picked, env.source_mode, env.status, env.collected_at,
                      warnings, errors, list(env.reports))


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


__all__ = ["LiveDomain", "collect_stays_flights", "dedupe_flights", "flight_key", "pick_flights",
           "pick_stays", "source_counts", "usable"]
