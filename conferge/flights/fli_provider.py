"""Google Flights through fli (punitarani/fli, MIT, PyPI ``flights``): secondary flight source.

Ranked behind the Bright Data Web Unlocker itineraries (source tier 2, a fallback). One
attempt only: fli's own tenacity retries are bypassed, the whole search (outbound list plus
one return-leg request per expanded outbound) is bounded by ``timeout_s``.

Prices are never guessed. In a round-trip search Google prices each return option with the
total for that outbound + return pair: when present it is stored as ``total_price`` and shown
as ``quoted_total``. When only the outbound row carries a price it is kept verbatim in
``raw_price_text`` and shown as ``indicative``; with no price at all, none is stored.
"""

from __future__ import annotations

import asyncio
import re
import types
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any
from urllib.parse import quote

from conferge.core.schemas import FlightOffer, RunReport, SourceEvidence
from conferge.flights.normalize import (
    NormalizationError,
    RawOffer,
    RawSegment,
    RawSlice,
    build_offer,
)

PROVIDER = "google_flights_fli"
MAX_ITINERARIES = 15
TIMEOUT_S = 20.0
OUTBOUNDS_EXPANDED = 5  # one return-leg request per expanded outbound
INDICATIVE_PREFIX = "outbound row price "


def search_url(origin: str, destination: str, depart: date, back: date) -> str:
    q = f"Flights from {origin} to {destination} on {depart.isoformat()} through {back.isoformat()}"
    return f"https://www.google.com/travel/flights?q={quote(q)}&curr=USD&hl=en"


def _segment(leg: Any) -> RawSegment:
    def code(v: Any) -> str | None:
        return getattr(v, "name", None) or (str(v) if v else None)

    airline = code(leg.airline)
    return RawSegment(
        origin=code(leg.departure_airport), destination=code(leg.arrival_airport),
        departure=leg.departure_datetime, arrival=leg.arrival_datetime,
        marketing_carrier=airline,
        operating_carrier=code(leg.operating_airline) if leg.operating_airline else None,
        flight_number=f"{airline}{leg.flight_number}" if airline and leg.flight_number else None,
        aircraft=leg.aircraft, duration_minutes=leg.duration,
    )


def _amount(value: Any) -> str | None:
    if value is None:
        return None
    return str(Decimal(str(value)).quantize(Decimal("0.01")))


def offer_from_pair(outbound: Any, inbound: Any, *, url: str, collected_at: datetime) -> FlightOffer:
    """One round-trip FlightOffer from a fli (outbound, return) pair."""
    total = _amount(getattr(inbound, "price", None))
    out_price = _amount(getattr(outbound, "price", None))
    currency = getattr(inbound, "currency", None) or getattr(outbound, "currency", None) or "USD"
    evidence = [SourceEvidence(provider=PROVIDER, source_mode="live", source_url=url,
                               collected_at=collected_at, raw_ref="fli:GetShoppingResults")]
    raw = RawOffer(
        provider=PROVIDER, trip_type="round_trip",
        slices=[RawSlice(segments=[_segment(x) for x in outbound.legs], duration_minutes=outbound.duration),
                RawSlice(segments=[_segment(x) for x in inbound.legs], duration_minutes=inbound.duration)],
        price=total, currency=currency if total else None,
        price_scope="total_all_passengers" if total else "unknown",
        booking_url=url, booking_url_type="google_flights_search", evidence=evidence,
    )
    # The round-trip total fli returns is stored as quoted_total (no display rewrite).
    offer = build_offer(raw, collected_at, price_status="quoted_total")
    if total is None and out_price is not None:
        offer = offer.model_copy(update={"raw_price_text": f"{INDICATIVE_PREFIX}{out_price} {currency}"})
    return offer


_RPC_ERROR = re.compile(r'\["wrb\.fr",null(?:,null)*,\[(\d+)\]')


def empty_reason(body: str | None) -> str:
    """Why Google gave fli no flight rows, read from the last response body."""
    if body and (m := _RPC_ERROR.search(body)):
        return f"Google answered without flight data (RPC error {m.group(1)}: request rejected)"
    return "fli returned no itinerary"


def _search(origin: str, destination: str, depart: date, back: date, *, adults: int,
            timeout_s: float, max_itineraries: int) -> tuple[list[tuple[Any, Any]], str | None]:
    from fli.models import (
        Airport,
        FlightSearchFilters,
        FlightSegment,
        PassengerInfo,
        SeatType,
        SortBy,
        TripType,
    )
    from fli.search import SearchFlights
    from fli.search import client as fli_client

    filters = FlightSearchFilters(
        trip_type=TripType.ROUND_TRIP, passenger_info=PassengerInfo(adults=adults),
        flight_segments=[
            FlightSegment(departure_airport=[[Airport[origin], 0]],
                          arrival_airport=[[Airport[destination], 0]], travel_date=depart.isoformat()),
            FlightSegment(departure_airport=[[Airport[destination], 0]],
                          arrival_airport=[[Airport[origin], 0]], travel_date=back.isoformat()),
        ],
        seat_type=SeatType.ECONOMY, sort_by=SortBy.CHEAPEST,
    )
    fli_client.REQUEST_TIMEOUT = timeout_s
    search = SearchFlights()
    # One attempt: call the undecorated methods, bypassing fli's 3-attempt tenacity retry.
    raw_post = type(search.client).post.__wrapped__
    last: dict[str, str] = {}

    def post(self: Any, *args: Any, **kwargs: Any) -> Any:
        response = raw_post(self, *args, **kwargs)
        last["body"] = response.text[:2000]
        return response

    search.client.post = types.MethodType(post, search.client)  # type: ignore[method-assign]
    search.client.get = types.MethodType(type(search.client).get.__wrapped__, search.client)  # type: ignore[method-assign]
    pairs = search.search(filters, top_n=OUTBOUNDS_EXPANDED, currency="USD", language="en", country="US") or []
    out = [p for p in pairs if isinstance(p, tuple) and len(p) == 2]
    priced = sorted(out, key=lambda p: (p[1].price is None, p[1].price or 0.0))
    return priced[:max_itineraries], (None if out else empty_reason(last.get("body")))


async def search_round_trip(origin: str = "JFK", destination: str = "SFO", *,
                            depart: date = date(2026, 10, 27), back: date = date(2026, 10, 30),
                            adults: int = 1, timeout_s: float = TIMEOUT_S,
                            max_itineraries: int = MAX_ITINERARIES) -> tuple[list[FlightOffer], RunReport]:
    started = datetime.now(timezone.utc)
    url = search_url(origin, destination, depart, back)

    def report(status: str, offers: list[FlightOffer], fetched: int, errors: list[str],
               warnings: list[str]) -> RunReport:
        return RunReport(provider=PROVIDER, started_at=started,
                         finished_at=max(datetime.now(timezone.utc), started),
                         status=status,  # type: ignore[arg-type]
                         termination="exhausted" if status == "ok" else "error",
                         source_mode="live", fetched_count=max(fetched, len(offers)),
                         unique_count=len(offers), errors=errors, warnings=warnings)

    try:
        pairs, why_empty = await asyncio.wait_for(asyncio.to_thread(
            _search, origin, destination, depart, back, adults=adults, timeout_s=timeout_s,
            max_itineraries=max_itineraries), timeout=timeout_s)
    except ImportError:
        return [], report("failed", [], 0, ["fli not installed (PyPI package flights)"], [])
    except (TimeoutError, asyncio.TimeoutError):
        return [], report("failed", [], 0, [f"fli timeout after {timeout_s:.0f}s"], [])
    except Exception as exc:  # noqa: BLE001 - blocked or changed page: visible, never invented
        return [], report("failed", [], 0, [f"fli {type(exc).__name__}: {str(exc)[:160]}"], [])
    collected = datetime.now(timezone.utc)
    offers, warnings = [], []
    for outbound, inbound in pairs:
        try:
            offers.append(offer_from_pair(outbound, inbound, url=url, collected_at=collected))
        except NormalizationError as exc:
            warnings.append(f"skipped itinerary: {exc}")
    status = "ok" if offers else "failed"
    return offers, report(status, offers, len(pairs),
                          [] if offers else [why_empty or "fli returned no usable itinerary"], warnings)


__all__ = ["PROVIDER", "offer_from_pair", "search_round_trip", "search_url"]
