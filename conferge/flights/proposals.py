"""Proactive date proposals (consumed by window 11).

Search the requested dates plus departure one day earlier and return one day
later. Propose an alternative when its cheapest observed price is lower by
more than the threshold (default 80 USD, same currency only), or when an
event the day before arrival justifies arriving earlier. Prices compared are
indicative metasearch observations, which the proposal says explicitly.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict

from conferge.core.schemas import FlightOffer
from conferge.flights.airports import airports_for
from conferge.flights.dedupe import cheapest
from conferge.flights.service import FlightSearchQuery, FlightService

THRESHOLD_USD = Decimal("80")


class FlightProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["depart_day_before", "return_day_after"]
    departure_date: date
    return_date: date
    reason: str
    currency: str | None = None
    base_price: str | None = None
    alternative_price: str | None = None
    saving: str | None = None
    base_offer_ids: list[str] = []
    alternative_offer_ids: list[str] = []
    source_mode: Literal["live", "cached", "fixture", "mixed"]
    warnings: list[str] = []


def trip_price(
    offers: list[FlightOffer], origin_iatas: set[str], currency: str = "USD"
) -> tuple[Decimal | None, list[str], str | None]:
    """Cheapest round trip, else cheapest outbound + cheapest return one-way.

    Returns (price, offer ids, warning). One-way fares of both directions are
    never mixed into a single "cheapest" value.
    """
    best_rt = cheapest([o for o in offers if o.trip_type == "round_trip"], currency)
    if best_rt:
        return Decimal(best_rt.total_price), [best_rt.id], None
    one_way = [o for o in offers if o.trip_type == "one_way"]
    out = cheapest([o for o in one_way if o.slices[0].segments[0].origin_iata in origin_iatas],
                   currency)
    back = cheapest([o for o in one_way
                     if o.slices[0].segments[0].origin_iata not in origin_iatas], currency)
    if out and back:
        total = Decimal(out.total_price) + Decimal(back.total_price)
        return total, [out.id, back.id], "sum_of_two_one_way_fares: separate tickets"
    return None, [], None


def compare_dates(
    kind: Literal["depart_day_before", "return_day_after"],
    base_query: FlightSearchQuery, base: list[FlightOffer], alternative: list[FlightOffer],
    *, source_mode: str, currency: str = "USD", threshold: Decimal = THRESHOLD_USD,
    event_day_before: bool = False,
) -> FlightProposal | None:
    dep = base_query.departure_date - timedelta(days=1 if kind == "depart_day_before" else 0)
    ret = base_query.return_date + timedelta(days=1 if kind == "return_day_after" else 0)
    origins = set(airports_for(base_query.origin_city,
                               include_secondary=base_query.include_secondary))
    base_price, base_ids, w_base = trip_price(base, origins, currency)
    alt_price, alt_ids, w_alt = trip_price(alternative, origins, currency)
    warnings = ["price_indicative: metasearch observations, not guaranteed fares"]
    warnings += list(dict.fromkeys(w for w in (w_base, w_alt) if w))
    saving: Decimal | None = None
    if base_price is not None and alt_price is not None:
        saving = base_price - alt_price
    priced_reason = saving is not None and saving > threshold
    event_reason = kind == "depart_day_before" and event_day_before
    if not (priced_reason or event_reason):
        return None
    reasons = []
    if priced_reason:
        reasons.append(f"cheaper by {saving} {currency} (threshold {threshold})")
    if event_reason:
        reasons.append("an event the day before the conference justifies arriving earlier")
    if saving is None:
        warnings.append("price_comparison_unavailable: missing priced offers in " + currency)
    return FlightProposal(
        kind=kind, departure_date=dep, return_date=ret, reason="; ".join(reasons),
        currency=currency if saving is not None else None,
        base_price=str(base_price) if base_price is not None else None,
        alternative_price=str(alt_price) if alt_price is not None else None,
        saving=str(saving) if saving is not None else None,
        base_offer_ids=base_ids, alternative_offer_ids=alt_ids,
        source_mode=source_mode, warnings=warnings,
    )


async def propose_alternatives(
    service: FlightService, query: FlightSearchQuery, *, event_day_before: bool = False,
    threshold: Decimal = THRESHOLD_USD, allow_fixture: bool = False,
) -> list[FlightProposal]:
    base = await service.search(query, allow_fixture=allow_fixture)
    proposals: list[FlightProposal] = []
    for kind, update in (
        ("depart_day_before", {"departure_date": query.departure_date - timedelta(days=1)}),
        ("return_day_after", {"return_date": query.return_date + timedelta(days=1)}),
    ):
        alt_query = query.model_copy(update=update)
        alt = await service.search(alt_query, allow_fixture=allow_fixture)
        mode = base.source_mode if base.source_mode == alt.source_mode else "mixed"
        proposal = compare_dates(kind, query, base.items, alt.items, source_mode=mode,
                                 threshold=threshold, event_day_before=event_day_before)
        if proposal:
            proposals.append(proposal)
    return proposals
