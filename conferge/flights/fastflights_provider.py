"""fast-flights (AWeirdDev/flights, MIT) provider: public Google Flights page.

Verified 2026-10-24 against fast-flights 3.1.0 at commit 7c105db installed
locally (it is not a project dependency; pyproject is owned by window 0, a
dependency proposal is in the PR). Without the package every call returns a
failed RunReport.

Facts observed on the live page: a round-trip query only lists outbound
options (with a round-trip price) and no flight numbers. A round trip cannot
be built from it without inventing the return slice, so this provider runs two
one-way searches and returns `one_way` offers, each with its own observed
price. Segment times are local (date, time) tuples localized with the airport
zone. Routed through `fast_flights.integrations.BrightData` (a SERP zone) when
BRIGHTDATA_API_KEY and BRIGHTDATA_SERP_ZONE are set, otherwise direct.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Callable
from datetime import date, datetime, timezone
from typing import Any

from conferge.core.schemas import FlightOffer, RunReport, SourceEvidence
from conferge.flights.normalize import (
    NormalizationError,
    RawOffer,
    RawSegment,
    RawSlice,
    build_offer,
    parse_duration,
)

PROVIDER = "fast_flights_google_flights"
NOT_INSTALLED = "fast-flights not installed; dependency proposal pending window 0"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _get(obj: Any, *names: str) -> Any:
    for name in names:
        value = obj.get(name) if isinstance(obj, dict) else getattr(obj, name, None)
        if value not in (None, "", [], ()):
            return value
    return None


def _code(airport: Any) -> str | None:
    if isinstance(airport, str):
        return airport.strip().upper() or None
    value = _get(airport, "code", "iata", "id")
    if value is None and airport is not None:
        value = getattr(airport, "value", None) or getattr(airport, "name", None)
    return str(value).strip().upper() if value else None


def _when(value: Any) -> Any:
    """Accept datetime, ISO string, or v3 SimpleDatetime(date=(y,m,d), time=(h,m))."""
    if value is None or isinstance(value, (datetime, str)):
        return value
    day, clock = _get(value, "date"), _get(value, "time")
    try:
        if (isinstance(day, (tuple, list)) and len(day) >= 3
                and isinstance(clock, (tuple, list)) and clock):
            hour, minute = (list(clock) + [0])[:2]
            return datetime(int(day[0]), int(day[1]), int(day[2]), int(hour), int(minute))
    except (TypeError, ValueError):
        return None
    return None


def _segment(raw: Any) -> RawSegment:
    number = _get(raw, "flight_number", "number")
    airline = _get(raw, "airline", "carrier")
    return RawSegment(
        origin=_code(_get(raw, "from_airport", "departure_airport", "origin")),
        destination=_code(_get(raw, "to_airport", "arrival_airport", "destination")),
        departure=_when(_get(raw, "departure", "departure_time")),
        arrival=_when(_get(raw, "arrival", "arrival_time")),
        marketing_carrier=str(airline) if airline else None,
        flight_number=str(number).replace(" ", "") if number else None,
        aircraft=_get(raw, "plane_type", "aircraft"),
        duration_minutes=parse_duration(_get(raw, "duration")),
    )


class FastFlightsProvider:
    def __init__(self, *, clock: Callable[[], datetime] = _now) -> None:
        self.clock = clock

    def _report(self, started: datetime, status: str, termination: str, *, fetched: int = 0,
                unique: int = 0, errors: list[str] | None = None,
                warnings: list[str] | None = None) -> RunReport:
        return RunReport(
            provider=PROVIDER, started_at=started, finished_at=max(self.clock(), started),
            status=status, termination=termination, source_mode="live",
            fetched_count=fetched, unique_count=unique, pages=1 if fetched else 0,
            errors=errors or [], warnings=warnings or [],
        )

    async def _one_way(self, origin: str, destination: str, day: date, adults: int,
                       cabin: str) -> tuple[list[Any], str]:
        from fast_flights import FlightQuery, Passengers, create_query, get_flights

        query = create_query(
            flights=[FlightQuery(date=day.isoformat(), from_airport=origin,
                                 to_airport=destination)],
            trip="one-way", seat=cabin, passengers=Passengers(adults=adults),
            currency="USD", language="en-US",
        )
        key, zone = os.environ.get("BRIGHTDATA_API_KEY"), os.environ.get("BRIGHTDATA_SERP_ZONE")
        if key and zone:
            from fast_flights.integrations import BrightData

            result = await asyncio.to_thread(
                get_flights, query, integration=BrightData(api_key=key, zone=zone))
        else:
            result = await asyncio.to_thread(get_flights, query)
        return list(result or []), query.url()

    def _offers(self, items: list[Any], search_url: str, collected_at: datetime,
                warnings: list[str]) -> list[FlightOffer]:
        offers: dict[str, FlightOffer] = {}
        for item in items:
            segments = [_segment(s) for s in (_get(item, "flights") or [])]
            code = _get(item, "type")
            if isinstance(code, str) and len(code) == 2 and code.isalnum():
                for seg in segments:  # single-carrier itinerary: Google gives its code
                    seg.marketing_carrier = code.upper()
            else:
                for seg in segments:
                    seg.marketing_carrier = None
            if not segments:
                continue
            raw = RawOffer(
                provider=PROVIDER, slices=[RawSlice(segments=segments)], trip_type="one_way",
                price=_get(item, "price"), currency="USD", price_scope="unknown",
                booking_url=search_url, booking_url_type="google_flights_search",
                evidence=[SourceEvidence(provider=PROVIDER, source_mode="live",
                                         source_url=search_url, collected_at=collected_at)],
            )
            try:
                offer = build_offer(raw, collected_at)
            except (NormalizationError, ValueError) as exc:
                warnings.append(f"normalization_failed: {exc}")
                continue
            offers.setdefault(offer.id, offer)
        return list(offers.values())

    async def search_round_trip(
        self, origin: str, destination: str, departure: date, return_date: date,
        *, adults: int = 1, cabin: str = "economy",
    ) -> tuple[list[FlightOffer], RunReport]:
        started = self.clock()
        try:
            import fast_flights  # noqa: F401
        except ImportError:
            return [], self._report(started, "failed", "error", errors=[NOT_INSTALLED])
        warnings = ["round_trip_as_two_one_way: Google lists only outbound options for a "
                    "round-trip query; offers are one-way fares, not a combined round trip"]
        if not (os.environ.get("BRIGHTDATA_API_KEY") and os.environ.get("BRIGHTDATA_SERP_ZONE")):
            warnings.append("fast_flights_direct: no Bright Data integration configured")
        results = await asyncio.gather(
            self._one_way(origin, destination, departure, adults, cabin),
            self._one_way(destination, origin, return_date, adults, cabin),
            return_exceptions=True,
        )
        collected_at = self.clock()
        offers: list[FlightOffer] = []
        errors: list[str] = []
        fetched = 0
        for direction, result in zip(("outbound", "return"), results, strict=True):
            if isinstance(result, BaseException):
                message = f"{direction} {type(result).__name__}: {str(result)[:200]}"
                key = os.environ.get("BRIGHTDATA_API_KEY")
                errors.append(message.replace(key, "***") if key else message)
                continue
            items, url = result
            fetched += len(items)
            found = self._offers(items, url, collected_at, warnings)
            if not found:
                errors.append(f"{direction}: zero offers")
            offers.extend(found)
        if not offers:
            return [], self._report(started, "failed", "error", fetched=fetched,
                                    errors=errors or ["zero offers"], warnings=warnings)
        status, termination = ("degraded", "error") if errors else ("ok", "exhausted")
        return offers, self._report(started, status, termination, fetched=fetched,
                                    unique=min(len(offers), fetched), errors=errors,
                                    warnings=warnings)
