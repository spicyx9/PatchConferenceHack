"""Bright Data Google Flights scraper (dataset gd_mhng7wen1rw0a3gvpf).

Flow: discover_by=input_filters returns candidate URLs (only `url` is
guaranteed), then collect_by_url on those URLs returns `pricing`, `providers`
and `legs`. One input per request keeps calls synchronous; pairs run in
parallel at the service level.

The sub-fields of `pricing`, `legs` and `providers` are not publicly
documented and public examples disagree, so `record_to_raw_offer` accepts
several key spellings and reports `schema_changed` when nothing matches. It
must be checked against the first real response (make probe-flights).
"""

from __future__ import annotations

import asyncio
import hashlib
import re
from collections.abc import Callable
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

from conferge.core.brightdata import BrightDataClient, BrightDataError
from conferge.core.schemas import (
    DiscoveryQuery,
    FlightOffer,
    DiscoveryResult,
    RunReport,
    SourceEvidence,
    SourceRecord,
    SourceRef,
)
from conferge.flights.airports import timezone_for
from conferge.flights.normalize import (
    RawOffer,
    RawSegment,
    NormalizationError,
    RawSlice,
    build_offer,
    classify_url,
    parse_duration,
)

DATASET_ID = "gd_mhng7wen1rw0a3gvpf"
PROVIDER = "brightdata_google_flights"
_CABINS = {"economy": "Economy", "premium_economy": "Premium economy",
           "business": "Business", "first": "First"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _pick(data: Any, *paths: str) -> Any:
    """First non-empty value among dotted paths."""
    for path in paths:
        value = data
        for part in path.split("."):
            if isinstance(value, dict):
                value = value.get(part)
            else:
                value = None
                break
        if value not in (None, "", [], {}):
            return value
    return None


def build_input(
    origin: str, destination: str, departure: date, return_date: date | None,
    *, adults: int = 1, cabin: str = "economy",
) -> dict[str, Any]:
    # Decision: the live validator is reported (S1xinch/flight-finder) to reject the
    # documented snake_case values and accept Google labels ("Round trip", "Economy").
    return {
        "origin": origin, "destination": destination,
        "departure": departure.isoformat(),
        "return": return_date.isoformat() if return_date else "",
        "trip_type": "Round trip" if return_date else "One way",
        "adults": adults, "children": 0, "infants_in_seat": 0, "infants_on_lap": 0,
        "cabin": _CABINS.get(cabin.lower(), cabin),
        "currency": "USD", "country": "us",
    }


def _record_id(row: dict[str, Any]) -> str:
    explicit = _pick(row, "itinerary_id", "id")
    if explicit:
        return str(explicit)
    basis = str(row.get("url") or sorted(row.items()))
    return "bd-" + hashlib.sha256(basis.encode()).hexdigest()[:16]


def _http_url(value: Any) -> str | None:
    return value if isinstance(value, str) and value.startswith(("http://", "https://")) else None


def has_itinerary_data(row: dict[str, Any]) -> bool:
    return bool(_pick(row, "legs", "pricing", "price"))


class BrightDataFlightsSource:
    """Implements `conferge.core.contracts.Source` for Google Flights."""

    def __init__(
        self, client: BrightDataClient | None = None, *,
        dataset_id: str = DATASET_ID, poll_interval: float = 3.0, max_polls: int = 20,
        clock: Callable[[], datetime] = _now,
    ) -> None:
        self.client = client or BrightDataClient.from_env()
        self.dataset_id = dataset_id
        self.poll_interval = poll_interval
        self.max_polls = max_polls
        self.clock = clock

    async def _run(self, inputs: list[dict[str, Any]], method: str, limit: int | None):
        out = await self.client.scrape_dataset(
            self.dataset_id, inputs, method=method, limit_per_input=limit
        )
        polls = 0
        while out.status == "running" and out.snapshot_id and polls < self.max_polls:
            await asyncio.sleep(self.poll_interval)
            out = await self.client.snapshot_results(out.snapshot_id)
            polls += 1
        return out

    def _rows(self, data: Any) -> tuple[list[dict[str, Any]], list[str]]:
        rows = data if isinstance(data, list) else [data] if isinstance(data, dict) else []
        good, errors = [], []
        for row in rows:
            if not isinstance(row, dict):
                continue
            if row.get("error") or row.get("error_code"):
                errors.append(f"record error: {row.get('error_code') or row.get('error')}")
                continue
            good.append(row)
        return good, errors

    def _record(self, row: dict[str, Any], collected_at: datetime, request_id: str | None):
        return SourceRecord(
            provider=PROVIDER, source_id=_record_id(row), source_mode="live",
            collected_at=collected_at, payload=row, source_url=_http_url(row.get("url")),
            request_id=request_id,
            content_hash=hashlib.sha256(repr(sorted(row.items())).encode()).hexdigest()[:16],
        )

    async def discover(self, query: DiscoveryQuery) -> DiscoveryResult:
        started = self.clock()
        f = query.filters
        origin, destination = f.get("origin"), f.get("destination")
        departure = query.start_date or f.get("departure")
        if not (origin and destination and departure):
            raise ValueError("flights discovery needs filters origin, destination and start_date")
        return_date = query.end_date if f.get("trip_type", "round_trip") == "round_trip" else None
        if isinstance(departure, str):
            departure = date.fromisoformat(departure)
        inputs = [build_input(origin, destination, departure, return_date,
                              adults=int(f.get("adults", 1)), cabin=f.get("cabin", "economy"))]
        try:
            out = await self._run(inputs, "discover_by_input_filters", query.limit)
        except BrightDataError as exc:
            return self._failed(started, str(exc), "error")
        if out.status == "running":
            return self._failed(started, "snapshot still running after poll budget", "error")
        collected_at = out.collected_at
        rows, row_errors = self._rows(out.data)
        items, seen = [], set()
        for row in rows:
            record = self._record(row, collected_at, out.snapshot_id)
            if record.source_id not in seen:
                seen.add(record.source_id)
                items.append(record)
        warnings = list(row_errors)
        if not items:
            status, termination = "failed", "exhausted"
            errors = ["zero results from discovery"]
        elif len(rows) >= query.limit:
            status, termination, errors = "degraded", "page_cap", []
            warnings.append(f"limit_per_input={query.limit} reached; more itineraries may exist")
        else:
            status, termination, errors = "ok", "exhausted", []
        report = RunReport(
            provider=PROVIDER, started_at=started, finished_at=max(self.clock(), started),
            status=status, termination=termination, source_mode="live",
            fetched_count=len(rows) + len(row_errors), unique_count=len(items), pages=1,
            errors=errors, warnings=warnings,
        )
        return DiscoveryResult(items=items, run_report=report, errors=errors)

    async def fetch_details(self, ref: SourceRef) -> SourceRecord:
        if ref.url is None:
            raise ValueError("collect_by_url needs a candidate URL")
        out = await self._run([{"url": str(ref.url)}], "collect_by_url", None)
        if out.status == "running":
            raise BrightDataError("collect_by_url snapshot still running after poll budget")
        rows, errors = self._rows(out.data)
        if not rows:
            raise BrightDataError(errors[0] if errors else "collect_by_url returned no record")
        record = self._record(rows[0], out.collected_at, out.snapshot_id)
        if record.source_url is None:
            record.source_url = ref.url
        return record

    def _failed(self, started: datetime, message: str, termination: str) -> DiscoveryResult:
        report = RunReport(
            provider=PROVIDER, started_at=started, finished_at=max(self.clock(), started),
            status="failed", termination=termination, source_mode="live",
            fetched_count=0, unique_count=0, errors=[message],
        )
        return DiscoveryResult(items=[], run_report=report, errors=[message])


_CLOCK = re.compile(r"^\s*(\d{1,2})(?::(\d{2}))?\s*([AaPp]\.?[Mm]\.?)?\s*(\+\d)?\s*$")


def _clock_candidates(text: Any, clock_24h: bool = False) -> list[tuple[int, int, int]]:
    """Possible (hour, minute, day_offset) for a clock string like '7', '10:15', '9:05 PM+1'.

    Without AM/PM an hour below 12 may be morning or evening, so both are kept
    unless the record proved it uses a 24 h clock.
    """
    if text in (None, ""):
        return []
    match = _CLOCK.match(str(text))
    if not match:
        return []
    hour, minute = int(match.group(1)), int(match.group(2) or 0)
    meridiem, plus = match.group(3), match.group(4)
    if hour > 23 or minute > 59:
        return []
    days = int(plus[1:]) if plus else 0
    if meridiem:
        if hour > 12 or hour == 0:
            return []
        hour = hour % 12 + (12 if meridiem.lower().startswith("p") else 0)
        return [(hour, minute, days)]
    hours = [hour] + ([hour + 12] if 1 <= hour < 12 and not clock_24h else [])
    return [(h, minute, days) for h in hours]


def resolve_segment_times(
    day: date | None, dep_clock: Any, arr_clock: Any, origin: str | None,
    destination: str | None, duration: int | None, not_before: datetime | None = None,
    clock_24h: bool = False,
) -> tuple[datetime | None, datetime | None, str | None]:
    """Turn date + local clocks into aware datetimes, only when unambiguous.

    A combination is accepted when arrival minus departure equals the reported
    travel time (5 minute tolerance) and, for later segments, departure is
    after the previous arrival and within 24 h. Exactly one distinct solution
    is required; otherwise both times stay None (never guessed).
    """
    dep_zone, arr_zone = timezone_for(origin), timezone_for(destination)
    if day is None or dep_zone is None or arr_zone is None or duration is None:
        return None, None, f"time_unresolved: {origin}-{destination} missing date, zone or duration"
    solutions = set()
    for dh, dm, dplus in _clock_candidates(dep_clock, clock_24h):
        for dep_shift in range(0, 3):
            dep = datetime.combine(day + timedelta(days=dep_shift + dplus), time(dh, dm),
                                   tzinfo=dep_zone)
            if not_before is not None and not (
                not_before <= dep <= not_before + timedelta(hours=24)
            ):
                continue
            if not_before is None and dep_shift:
                continue
            for ah, am, _ in _clock_candidates(arr_clock, clock_24h):
                for arr_shift in range(0, 3):
                    arr = datetime.combine(dep.date() + timedelta(days=arr_shift), time(ah, am),
                                           tzinfo=arr_zone)
                    delta = (arr - dep).total_seconds() / 60
                    if abs(delta - duration) <= 5:
                        solutions.add((dep, arr))
    if len(solutions) == 1:
        dep, arr = solutions.pop()
        return dep, arr, None
    reason = "no consistent" if not solutions else "ambiguous"
    return None, None, f"time_unresolved: {origin}-{destination} {reason} clock reading"


def uses_24h_clock(legs: list[Any]) -> bool:
    """True when a bare clock in the record reads 13..23 or 0, proving 24 h format."""
    for leg in legs:
        for seg in (leg.get("segments") or []) if isinstance(leg, dict) else []:
            for key in ("depart_time", "arrive_time", "departure_time", "arrival_time"):
                match = _CLOCK.match(str(seg.get(key) or "")) if isinstance(seg, dict) else None
                if match and not match.group(3) and (int(match.group(1)) >= 13
                                                     or int(match.group(1)) == 0):
                    return True
    return False


def _leg_date(leg: dict[str, Any]) -> date | None:
    value = _pick(leg, "date", "departure_date")
    if not value:
        return None
    try:
        # The leg date looks like midnight UTC but is the local calendar date.
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _carrier(raw: dict[str, Any]) -> str | None:
    value = _pick(raw, "marketing_code", "airline_code", "carrier_code",
                  "marketing_carrier", "airline_name", "airline")
    if isinstance(value, dict):
        value = value.get("iata") or value.get("name")
    return str(value) if value else None


def _slice(leg: dict[str, Any], warnings: list[str], clock_24h: bool = False) -> RawSlice:
    flights = _pick(leg, "segments", "flights")
    raw_segments = [s for s in flights if isinstance(s, dict)] if isinstance(flights, list) else []
    day = _leg_date(leg)
    segments: list[RawSegment] = []
    previous_arrival: datetime | None = None
    for raw in raw_segments:
        origin = _pick(raw, "depart_airport_iata", "departure_airport.id", "origin")
        destination = _pick(raw, "arrive_airport_iata", "arrival_airport.id", "destination")
        duration = parse_duration(str(_pick(raw, "segment_travel_time_text", "duration") or "")
                                  .replace("Travel time:", "").strip() or None)
        departure, arrival, warning = resolve_segment_times(
            day, _pick(raw, "depart_time", "departure_time"),
            _pick(raw, "arrive_time", "arrival_time"), origin, destination, duration,
            previous_arrival, clock_24h,
        )
        if warning:
            warnings.append(warning)
        previous_arrival = arrival
        number = _pick(raw, "flight_number", "flight_no")
        segments.append(RawSegment(
            origin=origin, destination=destination, departure=departure, arrival=arrival,
            marketing_carrier=_carrier(raw),
            operating_carrier=_pick(raw, "operating_carrier", "operated_by"),
            flight_number=str(number).replace(" ", "") if number else None,
            aircraft=_pick(raw, "aircraft_name", "aircraft", "airplane"),
            duration_minutes=duration,
        ))
    return RawSlice(
        segments=segments,
        duration_minutes=parse_duration(_pick(leg, "total_duration", "duration")),
        self_transfer=_pick(leg, "self_transfer", "is_self_transfer"),
    )


def _search_value(row: dict[str, Any], key: str) -> Any:
    search = row.get("search")
    if isinstance(search, dict) and search.get(key) not in (None, ""):
        return search[key]
    return row.get(f"search:{key}")


def record_to_raw_offer(record: SourceRecord) -> RawOffer:
    """Map a collect_by_url record; raises KeyError when the shape is unknown."""
    row = record.payload
    legs = row.get("legs")
    if not isinstance(legs, list) or not legs:
        raise KeyError("schema_changed: no legs in Bright Data record")
    pricing = row.get("pricing") if isinstance(row.get("pricing"), dict) else {}
    price = _pick(pricing, "best_total_price", "total_price", "total", "price")
    trip = _search_value(row, "trip_type")
    trip = str(trip).strip().lower().replace(" ", "_").replace("-", "_") if trip else None
    if trip not in {"one_way", "round_trip", "multi_city"}:
        trip = {1: "one_way", 2: "round_trip"}.get(len(legs), "multi_city")
    warnings: list[str] = []
    clock_24h = uses_24h_clock(legs)
    slices = [_slice(leg, warnings, clock_24h) for leg in legs if isinstance(leg, dict)]
    url = _http_url(row.get("url")) or (str(record.source_url) if record.source_url else None)
    evidence = [SourceEvidence(
        provider=PROVIDER, source_mode=record.source_mode, source_url=url,
        collected_at=record.collected_at, raw_ref=record.request_id,
        source_record_id=record.source_id,
    )]
    providers = row.get("providers")
    if isinstance(providers, list) and providers:
        names = [str(_pick(p, "provider_name", "name")) for p in providers if isinstance(p, dict)]
        warnings.append(f"booking_options_seen: {', '.join(n for n in names if n != 'None')}")
    return RawOffer(
        provider=PROVIDER, slices=slices, trip_type=trip,
        price=price, currency=_pick(pricing, "currency"),
        # Decision: Google shows the price for the requested passengers; with
        # adults=1 it is still recorded as unknown scope until verified live.
        price_scope="unknown",
        booking_url=url, booking_url_type=classify_url(url),
        evidence=evidence, warnings=warnings,
    )


async def search_round_trip(
    source: BrightDataFlightsSource, origin: str, destination: str, departure: date,
    return_date: date, *, adults: int = 1, cabin: str = "economy", collect_top: int = 3,
) -> tuple[list[FlightOffer], RunReport]:
    """Discovery (candidate URLs) then collect_by_url, then normalization.

    Discovery rows that already carry `legs` are normalized directly; URL-only
    rows are collected (at most `collect_top`, budget). Every failed collect or
    unmappable record is counted in the report, never silently dropped.
    """
    started = source.clock()
    query = DiscoveryQuery(
        domain="flights", start_date=departure, end_date=return_date, limit=10,
        filters={"origin": origin, "destination": destination, "adults": adults,
                 "cabin": cabin, "trip_type": "round_trip"},
    )
    discovery = await source.discover(query)
    report = discovery.run_report
    warnings, errors = list(report.warnings), list(report.errors)
    if not discovery.items:
        return [], report
    detailed: list[SourceRecord] = []
    to_collect: list[SourceRecord] = []
    for record in discovery.items:
        (detailed if has_itinerary_data(record.payload) else to_collect).append(record)
    skipped = to_collect[collect_top:]
    if skipped:
        warnings.append(f"collect_cap: {len(skipped)} candidate URL(s) not collected")
    results = await asyncio.gather(
        *(source.fetch_details(r.as_ref()) for r in to_collect[:collect_top]
          if r.source_url is not None),
        return_exceptions=True,
    )
    for result in results:
        if isinstance(result, BaseException):
            errors.append(f"collect_by_url failed: {result}")
        else:
            detailed.append(result)
    offers: list[FlightOffer] = []
    schema_misses = 0
    for record in detailed:
        try:
            raw = record_to_raw_offer(record)
            raw.price_scope = "unknown"
            offers.append(build_offer(raw, record.collected_at))
        except KeyError as exc:
            schema_misses += 1
            warnings.append(str(exc).strip("'\""))
        except (NormalizationError, ValueError) as exc:
            warnings.append(f"unmappable record {record.source_id}: {exc}")
    if not offers:
        status, termination = "failed", "schema_changed" if schema_misses else "error"
        errors.append("no normalized round-trip offer")
    elif errors or skipped or report.status != "ok" or len(offers) < len(detailed):
        status = "degraded"
        if errors:
            termination = "error"
        elif len(offers) < len(detailed):
            termination = "schema_changed"
        elif report.termination != "exhausted":
            termination = report.termination
        else:
            termination = "page_cap"
    else:
        status, termination = "ok", "exhausted"
    final = RunReport(
        provider=PROVIDER, started_at=started, finished_at=max(source.clock(), started),
        status=status, termination=termination, source_mode="live",
        fetched_count=report.fetched_count, unique_count=min(len(offers), report.fetched_count),
        pages=report.pages + len(results), expected_count=None,
        errors=errors, warnings=list(dict.fromkeys(warnings)),
    )
    return offers, final


class BrightDataFlightsProvider(BrightDataFlightsSource):
    """Source plus the round-trip pipeline used by the flight service."""

    async def search_round_trip(
        self, origin: str, destination: str, departure: date, return_date: date,
        *, adults: int = 1, cabin: str = "economy",
    ) -> tuple[list[FlightOffer], RunReport]:
        return await search_round_trip(self, origin, destination, departure, return_date,
                                       adults=adults, cabin=cabin)
