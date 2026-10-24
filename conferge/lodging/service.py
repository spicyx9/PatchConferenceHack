"""Parallel lodging search: discover, verify, normalize, distance, dedup, rank.

Bright Data first: the dataset and Web Unlocker sources run in parallel; the fallback
sources (pyairbnb) run only when none of them normalized a single stay.

Providers run concurrently (asyncio.gather); one failing provider never hides the others
and never crashes the run: it shows up as a failed RunReport. Caches (in memory):
- discovery results 6 h, keyed (provider, query dates/occupancy/currency/area);
- verified results 30 min (a verified quote older than that is downgraded on read).
Served-from-cache records are relabelled ``cached`` (never presented as fresh live).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from conferge.core.schemas import DataEnvelope, DiscoveryResult, Lodging, RunReport, SourceRecord
from conferge.lodging._common import now_utc, report, worst_status
from conferge.lodging.dedupe import DedupGroup, dedupe
from conferge.lodging.distance import distances, with_venue_distance
from conferge.lodging.models import LodgingQuery
from conferge.lodging.normalize import normalize, refresh_status, sort_key

logger = logging.getLogger(__name__)

DISCOVERY_TTL = timedelta(hours=6)
PROVIDER_TIMEOUT = 120.0  # one slow source becomes a failed report, never a dead search
VERIFY_TTL = timedelta(minutes=30)


@dataclass
class LodgingSearch:
    envelope: DataEnvelope[Lodging]
    groups: list[DedupGroup] = field(default_factory=list)
    distances: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


@dataclass
class _Entry:
    at: datetime
    result: DiscoveryResult
    verify_report: RunReport | None = None


def _as_cached(result: DiscoveryResult, age: timedelta) -> DiscoveryResult:
    items = [r.model_copy(update={"source_mode": "cached"}) if r.source_mode == "live" else r
             for r in result.items]
    rep = result.run_report.model_copy(update={
        "source_mode": "cached" if result.run_report.source_mode == "live"
        else result.run_report.source_mode,
        "warnings": [*result.run_report.warnings,
                     f"served from cache, age {int(age.total_seconds())} s"],
    })
    return DiscoveryResult(items=items, run_report=rep, errors=list(result.errors))


def default_sources() -> dict[str, Any]:
    """Bright Data first: the three datasets and the Web Unlocker search pages, in parallel."""
    from conferge.lodging.airbnb import AirbnbSource, BrightDataAirbnbBackend
    from conferge.lodging.booking import BookingSource
    from conferge.lodging.google_hotels import GoogleHotelsSource
    from conferge.lodging.google_hotels_direct import GoogleHotelsDirectSource
    from conferge.lodging.unlocker import UnlockerHotelsSource

    return {"booking": BookingSource(), "google_hotels": GoogleHotelsSource(),
            "airbnb": AirbnbSource(primary=BrightDataAirbnbBackend(), fallback=None),
            "unlocker": UnlockerHotelsSource(),
            # Secondary, labelled google_hotels_direct; shown after the datasets (tier 2).
            "google_hotels_direct": GoogleHotelsDirectSource()}


def default_fallback_sources() -> dict[str, Any]:
    """pyairbnb, used only when every Bright Data source normalized zero stays."""
    from conferge.lodging.airbnb import AirbnbSource, PyAirbnbBackend

    return {"airbnb_pyairbnb": AirbnbSource(primary=PyAirbnbBackend(), fallback=None)}


class LodgingService:
    def __init__(
        self, sources: dict[str, Any] | None = None, *, clock: Callable[[], datetime] = now_utc,
        fallback_sources: dict[str, Any] | None = None,
        provider_timeout: float = PROVIDER_TIMEOUT,
    ) -> None:
        self.provider_timeout = provider_timeout
        self._sources = sources if sources is not None else default_sources()
        if fallback_sources is None:
            fallback_sources = default_fallback_sources() if sources is None else {}
        self._fallbacks = fallback_sources
        self._clock = clock
        self._discovery: dict[tuple[Any, ...], _Entry] = {}
        self._verified: dict[tuple[Any, ...], _Entry] = {}

    async def aclose(self) -> None:
        for src in [*self._sources.values(), *self._fallbacks.values()]:
            close = getattr(src, "aclose", None)
            if close is not None:
                await close()

    async def _provider(self, name: str, src: Any, q: LodgingQuery) -> tuple[DiscoveryResult, RunReport | None]:
        key = (name, *q.cache_key(), q.verify_top)
        now = self._clock()
        hit = self._verified.get(key)
        if hit and now - hit.at <= VERIFY_TTL:
            return _as_cached(hit.result, now - hit.at), hit.verify_report
        started = now
        try:
            disc = self._discovery.get(key)
            if disc and now - disc.at <= DISCOVERY_TTL:
                result = disc.result
            else:
                result = await asyncio.wait_for(src.search(q), self.provider_timeout)
                if result.items:
                    self._discovery[key] = _Entry(self._clock(), result)
            verify_report = None
            verify = getattr(src, "verify", None)
            if verify is not None and result.items and q.verify_top > 0:
                try:
                    items, verify_report = await asyncio.wait_for(
                        verify(list(result.items), q), self.provider_timeout)
                except (asyncio.TimeoutError, TimeoutError):
                    # Discovery results stand; the re-check is reported as failed.
                    return result, report(f"{name}_verify", started, status="failed",
                                          termination="error",
                                          errors=[f"verify timeout after {self.provider_timeout:.0f}s"])
                result = DiscoveryResult(items=items, run_report=result.run_report,
                                         errors=list(result.errors))
                if verify_report.status != "failed":
                    self._verified[key] = _Entry(self._clock(), result, verify_report)
            return result, verify_report
        except (asyncio.TimeoutError, TimeoutError):
            rep = report(name, started, status="failed", termination="error",
                         errors=[f"timeout: no answer within {self.provider_timeout:.0f}s"])
            return DiscoveryResult(run_report=rep, errors=list(rep.errors)), None
        except Exception as exc:  # noqa: BLE001 - a broken provider is reported, not raised
            logger.warning("lodging.provider_failed", extra={"provider": name,
                                                             "error": type(exc).__name__})
            rep = report(name, started, status="failed", termination="error",
                         errors=[f"{type(exc).__name__}: {str(exc)[:200]}"])
            return DiscoveryResult(run_report=rep, errors=list(rep.errors)), None

    async def _tier(self, sources: dict[str, Any], q: LodgingQuery,
                    ) -> tuple[list[SourceRecord], list[RunReport], list[RunReport]]:
        outcomes = await asyncio.gather(*(self._provider(n, src, q) for n, src in sources.items()))
        reports: list[RunReport] = []
        verify_reports: list[RunReport] = []
        records: list[SourceRecord] = []
        for result, verify_report in outcomes:
            reports.append(result.run_report)
            if verify_report is not None:
                verify_reports.append(verify_report)
            records.extend(result.items)
        return records, reports, verify_reports

    async def search(self, q: LodgingQuery) -> LodgingSearch:
        records, reports, verify_reports = await self._tier(self._sources, q)
        found = self.assemble(records, q, reports, verify_reports)
        if found.envelope.items or not self._fallbacks:
            return found
        # Every primary (Bright Data) source came back empty: only now try the fallbacks.
        more, more_reports, more_verify = await self._tier(self._fallbacks, q)
        found = self.assemble([*records, *more], q, [*reports, *more_reports],
                              [*verify_reports, *more_verify])
        found.warnings.insert(0, "fallback used: no stay from Bright Data, "
                                 f"tried {', '.join(self._fallbacks)}")
        return found

    def assemble(
        self, records: list[SourceRecord], q: LodgingQuery, reports: list[RunReport],
        verify_reports: list[RunReport] | None = None,
    ) -> LodgingSearch:
        verify_reports = verify_reports or []
        warnings: list[str] = []
        now = self._clock()
        stays: list[Lodging] = []
        seen: set[str] = set()
        for record in records:
            try:
                stay = normalize(record, q, warnings=warnings, now=now)
            except Exception as exc:  # noqa: BLE001 - schema drift on one row is a warning
                warnings.append(f"{record.provider}:{record.source_id}: normalization failed "
                                f"({type(exc).__name__})")
                continue
            if stay is None or stay.id in seen:
                continue
            seen.add(stay.id)
            stays.append(with_venue_distance(refresh_status(stay, now=now), q.venue))
        stays, groups = dedupe(stays)
        stays.sort(key=sort_key)
        places = [q.venue, *q.venues]
        modes = {e.source_mode for s in stays for e in s.evidence[:1]}
        if not modes:
            modes = {r.source_mode for r in reports} or {"live"}
        status = worst_status(r.status for r in reports)
        if status == "ok" and any(r.status != "ok" for r in verify_reports):
            status = "degraded"
        if not stays and status != "failed":
            status = "degraded"
            warnings.append("no lodging normalized from any provider")
        errors = [f"{r.provider}: {e}" for r in [*reports, *verify_reports] for e in r.errors]
        envelope = DataEnvelope[Lodging](
            items=stays, source_mode=modes.pop() if len(modes) == 1 else "mixed",
            status=status, collected_at=now, reports=[*reports, *verify_reports], errors=errors,
        )
        return LodgingSearch(
            envelope=envelope, groups=groups,
            distances={s.id: distances(s, places) for s in stays}, warnings=warnings,
        )


def _coerce(query: Any) -> LodgingQuery:
    from conferge.core.schemas import DiscoveryQuery

    if isinstance(query, LodgingQuery):
        return query
    if isinstance(query, DiscoveryQuery):
        return LodgingQuery.from_discovery(query)
    if isinstance(query, dict):
        data = dict(query)
        if "lon" in data and "lng" not in data:
            data["lng"] = data.pop("lon")
        if "venues" in data:
            data["venues"] = [
                {"id": v.get("id") or f"place:{i}", "name": v.get("name") or f"place {i}",
                 "lat": v["lat"], "lng": v.get("lng", v.get("lon"))}
                for i, v in enumerate(data["venues"])
            ]
        return LodgingQuery.model_validate(data)
    raise TypeError("query must be LodgingQuery, DiscoveryQuery or dict")


async def run(query: Any, *, service: LodgingService | None = None) -> DataEnvelope[Lodging]:
    """Live search; failures surface as degraded/failed, never as silent fixtures."""
    q = _coerce(query)
    own = service is None
    svc = service or LodgingService()
    try:
        return (await svc.search(q)).envelope
    finally:
        if own:
            await svc.aclose()
