"""Flight search service: airport fan-out, provider router, cache, fixture opt-in.

Router per airport pair: Bright Data dataset snapshot (< 24 h, collected out of the demo
path) first, then Bright Data Web Unlocker
(Google Flights page); if they fail, return nothing or no priced offer, fast-flights;
then SerpApi. Every provider report is
kept in the envelope. A fixture is only returned when `allow_fixture=True`
was passed explicitly, and it is labelled `fixture` everywhere.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Sequence
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from conferge.core.schemas import DataEnvelope, FlightOffer, RunReport
from conferge.flights.airports import airport_pairs
from conferge.flights.dedupe import dedupe_offers

FIXTURE_PATH = Path(__file__).resolve().parents[2] / "fixtures" / "flights.json"
CACHE_TTL = timedelta(minutes=20)


class FlightProvider(Protocol):
    async def search_round_trip(
        self, origin: str, destination: str, departure: date, return_date: date,
        *, adults: int = 1, cabin: str = "economy",
    ) -> tuple[list[FlightOffer], RunReport]: ...


class FlightSearchQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    origin_city: str
    destination_city: str
    departure_date: date
    return_date: date
    adults: int = Field(default=1, ge=1, le=9)
    cabin: str = "economy"
    include_secondary: bool = False

    @model_validator(mode="after")
    def dates(self) -> FlightSearchQuery:
        if self.return_date < self.departure_date:
            raise ValueError("return_date must be >= departure_date")
        return self

    def cache_key(self) -> str:
        return self.model_dump_json()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def load_fixture_offers(path: Path = FIXTURE_PATH, *, explicit_opt_in: bool = False) -> list[FlightOffer]:
    """Load labelled fixture offers; refuses unless explicitly requested."""
    if not explicit_opt_in:
        raise RuntimeError("flight fixtures must be explicitly requested")
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("source_mode") != "fixture":
        raise ValueError("fixture file must declare source_mode=fixture")
    offers = [FlightOffer.model_validate(item) for item in data["offers"]]
    for offer in offers:
        if offer.price_status not in {"unknown", "cached"} and offer.total_price is not None:
            raise ValueError(f"fixture offer {offer.id} must not claim a live price")
        if any(e.source_mode != "fixture" for e in offer.evidence) or not offer.evidence:
            raise ValueError(f"fixture offer {offer.id} must carry fixture evidence")
    return offers


def default_providers() -> list[tuple[str, FlightProvider]]:
    from conferge.flights.fastflights_provider import FastFlightsProvider
    from conferge.flights.serpapi_provider import SerpApiFlightsProvider
    from conferge.flights.unlocker_provider import GoogleFlightsUnlockerProvider

    from conferge.flights.snapshot_provider import GoogleFlightsSnapshotProvider

    # The live dataset takes minutes: scripts/probes/flights_collect.py runs it out of the
    # demo path and the router reads its snapshot (< 24 h). BrightDataFlightsProvider stays
    # available for probes.
    return [
        ("brightdata_snapshot", GoogleFlightsSnapshotProvider()),
        ("brightdata_unlocker", GoogleFlightsUnlockerProvider()),
        ("fastflights", FastFlightsProvider()),
        ("serpapi", SerpApiFlightsProvider()),
    ]


class FlightService:
    def __init__(
        self, providers: Sequence[tuple[str, FlightProvider]] | None = None, *,
        cache_ttl: timedelta = CACHE_TTL, clock: Callable[[], datetime] = _now,
        fixture_path: Path = FIXTURE_PATH, provider_timeout: float = 90.0,
    ) -> None:
        self._providers = list(providers) if providers is not None else None
        self.cache_ttl = cache_ttl
        self.clock = clock
        self.fixture_path = fixture_path
        self.provider_timeout = provider_timeout
        self._cache: dict[str, tuple[datetime, DataEnvelope[FlightOffer]]] = {}

    @property
    def providers(self) -> list[tuple[str, FlightProvider]]:
        if self._providers is None:
            self._providers = default_providers()
        return self._providers

    async def _call(
        self, name: str, provider: FlightProvider, origin: str, destination: str,
        q: FlightSearchQuery,
    ) -> tuple[list[FlightOffer], RunReport]:
        started = self.clock()
        try:
            return await asyncio.wait_for(
                provider.search_round_trip(origin, destination, q.departure_date, q.return_date,
                                           adults=q.adults, cabin=q.cabin),
                timeout=self.provider_timeout,
            )
        except Exception as exc:  # provider bug or timeout must stay visible, not crash
            kind = "timeout" if isinstance(exc, (asyncio.TimeoutError, TimeoutError)) else "error"
            report = RunReport(
                provider=name, started_at=started, finished_at=max(self.clock(), started),
                status="failed", termination="error", source_mode="live",
                fetched_count=0, unique_count=0,
                errors=[f"{name} {kind}: {type(exc).__name__}"],
                warnings=[f"pair {origin}-{destination}"],
            )
            return [], report

    async def _search_pair(
        self, origin: str, destination: str, q: FlightSearchQuery
    ) -> tuple[list[FlightOffer], list[RunReport]]:
        """Try providers in order until one returns a priced offer."""
        reports: list[RunReport] = []
        unpriced: list[FlightOffer] = []
        tag = f"pair {origin}-{destination}"
        for name, provider in self.providers:
            offers, report = await self._call(name, provider, origin, destination, q)
            if tag not in report.warnings:
                report = report.model_copy(update={"warnings": [*report.warnings, tag]})
            reports.append(report)
            if any(o.total_price is not None for o in offers):
                return unpriced + offers, reports
            unpriced.extend(offers)  # kept, but the next provider is still tried
        return unpriced, reports

    async def search(
        self, q: FlightSearchQuery, *, allow_fixture: bool = False
    ) -> DataEnvelope[FlightOffer]:
        key = q.cache_key()
        cached = self._cache.get(key)
        if cached and cached[0] > self.clock():
            return cached[1]
        pairs = airport_pairs(q.origin_city, q.destination_city,
                              include_secondary=q.include_secondary)
        results = await asyncio.gather(*(self._search_pair(o, d, q) for o, d in pairs))
        offers = dedupe_offers(o for pair_offers, _ in results for o in pair_offers)
        reports = [r for _, pair_reports in results for r in pair_reports]
        errors = [e for r in reports for e in r.errors]
        offers.sort(key=_sort_key)
        if offers:
            # ok only when every provider called reported ok: a failed primary
            # stays visible as degraded even when a fallback filled the pair.
            all_ok = all(r.status == "ok" for r in reports)
            envelope = DataEnvelope[FlightOffer](
                items=offers, source_mode="live", status="ok" if all_ok else "degraded",
                collected_at=self.clock(), reports=reports, errors=errors,
            )
            self._cache[key] = (self.clock() + self.cache_ttl, envelope)
            return envelope
        if allow_fixture:
            fixture = load_fixture_offers(self.fixture_path, explicit_opt_in=True)
            return DataEnvelope[FlightOffer](
                items=[o for o in fixture if _matches(o, q)], source_mode="fixture",
                status="degraded", collected_at=self.clock(), reports=reports,
                errors=[*errors, "FIXTURE: live collection failed; explicit fixture fallback"],
            )
        return DataEnvelope[FlightOffer](
            items=[], source_mode="live", status="failed", collected_at=self.clock(),
            reports=reports, errors=errors or ["no flight offers collected"],
        )


def _sort_key(offer: FlightOffer) -> tuple[int, float]:
    if offer.total_price is None:
        return (1, 0.0)
    return (0, float(offer.total_price))


def _matches(offer: FlightOffer, q: FlightSearchQuery) -> bool:
    """Fixture filter: slice departure dates must equal the requested dates."""
    wanted = [q.departure_date, q.return_date]
    for flight_slice, day in zip(offer.slices, wanted, strict=False):
        dep = flight_slice.segments[0].departure_at
        if dep is not None and dep.date() != day:
            return False
    return True


async def run(query: dict[str, Any], *, service: FlightService | None = None,
              allow_fixture: bool = False) -> DataEnvelope[FlightOffer]:
    """Entry point: {origin_city, destination_city, departure_date, return_date, adults, cabin}."""
    return await (service or FlightService()).search(
        FlightSearchQuery.model_validate(query), allow_fixture=allow_fixture
    )


def load_fixture(path: Path = FIXTURE_PATH) -> DataEnvelope[FlightOffer]:
    """Explicit fixture loader: calling it is the opt-in; everything is labelled fixture."""
    offers = load_fixture_offers(path, explicit_opt_in=True)
    return DataEnvelope[FlightOffer](
        items=offers, source_mode="fixture", status="ok",
        collected_at=min(o.collected_at for o in offers),
    )
