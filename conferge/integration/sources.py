"""Collect normalized slices from every merged source window.

Two explicit paths, never mixed silently:

* ``fixture_slices`` opts in to each window's labelled fixture loader. Every
  record keeps ``source_mode="fixture"``.
* ``live_slices`` calls each window's live ``run``/``collect``. A failure is a
  ``failed`` slice with zero items and the error text. It is **not** replaced by
  the fixture here; the caller decides, and the replacement stays labelled.

Sources are isolated from each other: live runners go through
``asyncio.gather(return_exceptions=True)``, so one adapter raising becomes one
``failed`` slice with a sanitized message while the others complete.
``overall_report`` turns the slices into one RunReport (``degraded`` when some
failed). Each slice carries its own ``duration_s``.

Side-event sources (Luma, Partiful, Eventbrite) are normalized with
``conference_id=None``: proximity in time and place is not evidence of a
relation to the anchor conference, and the graph would otherwise draw a
``PART_OF`` edge for any party in San Francisco that week.
"""

from __future__ import annotations

import asyncio
import re
import time
from collections.abc import Awaitable, Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any

from conferge.core.schemas import (
    Company,
    Conference,
    DataEnvelope,
    DiscoveryQuery,
    Event,
    Person,
    RunReport,
    RunStatus,
)

CONFERENCE_ID = "github-universe-2026"
WINDOW = (date(2026, 10, 27), date(2026, 10, 30))
FORT_MASON = (37.8060, -122.4320)


@dataclass
class SourceSlice:
    name: str
    window: str
    attempted: str
    """``fixture`` or ``live``: which path produced this slice."""
    source_mode: str
    status: RunStatus
    events: list[Event] = field(default_factory=list)
    people: list[Person] = field(default_factory=list)
    companies: list[Company] = field(default_factory=list)
    conference: Conference | None = None
    reports: list[RunReport] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    collected_at: datetime | None = None
    duration_s: float | None = None
    """Wall time of this source's collection (loader or live runner), seconds."""

    @property
    def count(self) -> int:
        return len(self.events) + len(self.people) + len(self.companies)


_SECRET = re.compile(r"(?i)\b(bearer|token|api[_-]?key|key|password|secret|authorization|cookie)"
                     r"(\s*[=:]\s*|\s+)[^\s&,;'\"]+")


def sanitize(message: str, limit: int = 200) -> str:
    """Error text safe to show: no URL query strings, no credential values, one line, capped."""
    text = re.sub(r"(https?://[^\s?#'\"]+)[?#][^\s'\"]*", r"\1?…", message)
    text = _SECRET.sub(lambda m: f"{m.group(1)}=<redacted>", text)
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def describe(exc: BaseException, timeout: float | None = None) -> str:
    """Sanitized one-line reason for a source that raised."""
    if isinstance(exc, (TimeoutError, asyncio.TimeoutError)) and timeout is not None:
        return f"timeout after {timeout:.0f}s"
    if isinstance(exc, ImportError):
        return sanitize(f"not importable: {exc}")
    return sanitize(f"{type(exc).__name__}: {exc}")


def _failed(name: str, window: str, attempted: str, error: str) -> SourceSlice:
    """Failed slice with its own failed RunReport, so the pipeline panel shows a row for it."""
    mode = "fixture" if attempted == "fixture" else "live"
    now = datetime.now(timezone.utc)
    reason = sanitize(error, 300)
    report = RunReport(provider=name, started_at=now, finished_at=now, status="failed",
                       termination="error", source_mode=mode, fetched_count=0, unique_count=0,
                       errors=[reason])
    return SourceSlice(name, window, attempted, mode, "failed", reports=[report], errors=[reason],
                       collected_at=now)


def overall_report(slices: list[SourceSlice], started_at: datetime | None = None) -> RunReport:
    """One RunReport for the whole collection: ok, degraded when some sources failed, failed
    when none produced records."""
    now = datetime.now(timezone.utc)
    failed = [s for s in slices if s.status == "failed"]
    usable = [s for s in slices if s.count]
    status: RunStatus = ("failed" if not usable else
                         "degraded" if failed or any(s.status == "degraded" for s in slices) else "ok")
    modes = {s.source_mode for s in usable}
    return RunReport(
        provider="sources", started_at=min(started_at or now, now), finished_at=now,
        status=status, termination="exhausted" if status == "ok" else "error",
        source_mode="live" if "live" in modes else ("cached" if "cached" in modes else "fixture"),
        fetched_count=len(slices), unique_count=len(usable),
        errors=[f"{s.name}: {e}" for s in failed for e in s.errors],
        warnings=[f"{len(failed)} of {len(slices)} sources failed; the others are kept"] if failed else [],
    )


def _from_envelope(name: str, window: str, attempted: str,
                   env: DataEnvelope[Event]) -> SourceSlice:
    warnings = [w for r in env.reports for w in r.warnings]
    return SourceSlice(name, window, attempted, env.source_mode, env.status,
                       events=list(env.items), reports=list(env.reports),
                       errors=list(env.errors), warnings=warnings,
                       collected_at=env.collected_at)


# -- fixture path ---------------------------------------------------------------------


def _fixture_luma() -> SourceSlice:
    from conferge.events import luma

    result = luma.load_fixture(explicit_opt_in=True)
    events = [luma.normalize(r, conference_id=None) for r in result.items]
    return SourceSlice("luma", "01", "fixture", "fixture", result.run_report.status,
                       events=events, reports=[result.run_report], errors=list(result.errors),
                       warnings=list(result.run_report.warnings),
                       collected_at=result.run_report.finished_at)


def _fixture_partiful() -> SourceSlice:
    from conferge.events import partiful

    result = partiful.load_fixture(explicit_opt_in=True)
    events = [partiful.normalize(r, conference_id=None) for r in result.items]
    return SourceSlice("partiful", "01", "fixture", "fixture", result.run_report.status,
                       events=events, reports=[result.run_report], errors=list(result.errors),
                       warnings=list(result.run_report.warnings),
                       collected_at=result.run_report.finished_at)


def _records_slice(name: str, result: Any, events: list[Event],
                   errors: list[str]) -> SourceSlice:
    report = result.run_report
    status: RunStatus = "failed" if not events else report.status
    return SourceSlice(name, "02", "fixture", "fixture", status, events=events,
                       reports=[report], errors=list(result.errors) + errors,
                       warnings=list(report.warnings), collected_at=report.finished_at)


def _fixture_eventbrite() -> SourceSlice:
    from conferge.events.eventbrite import load_fixture
    from conferge.events.eventbrite.normalize import normalize_records

    result = load_fixture(explicit_opt_in=True)
    events, errors = normalize_records(result.items, conference_id=None)
    return _records_slice("eventbrite", result, events, errors)


def _fixture_aggregators() -> SourceSlice:
    from conferge.events.aggregators import load_fixture
    from conferge.events.aggregators.normalize import normalize_records

    result = load_fixture(explicit_opt_in=True)
    events, errors = normalize_records(result.items, conference_id=CONFERENCE_ID,
                                       timezone_name="America/Los_Angeles",
                                       city="San Francisco")
    return _records_slice("aggregators", result, events, errors)


def _official_slice(attempted: str, collection: Any) -> SourceSlice:
    env = collection.events
    return SourceSlice(
        "official", "03", attempted, env.source_mode, env.status,
        events=list(env.items), people=list(collection.people.items),
        companies=list(collection.companies.items), conference=collection.conference,
        reports=list(env.reports), errors=list(env.errors),
        warnings=[w for r in env.reports for w in r.warnings] + list(collection.warnings),
        collected_at=env.collected_at,
    )


def _fixture_official() -> SourceSlice:
    from conferge.events import official

    return _official_slice("fixture", official.load_fixture(explicit_opt_in=True))


def _fixture_discovery() -> SourceSlice:
    from conferge.events import discovery

    # load_fixture is async; run it on its own loop so fixture_slices stays sync
    # and callable from inside a running loop (run_e2e).
    with ThreadPoolExecutor(max_workers=1) as pool:
        result = pool.submit(asyncio.run, discovery.load_fixture(explicit_opt_in=True)).result()
    # SERP hits are candidate URLs, not events: no record enters the dataset.
    report = result.run_report
    return SourceSlice("discovery", "04", "fixture", "fixture", report.status,
                       reports=[report], errors=list(result.errors),
                       warnings=[f"{len(result.items)} candidate URLs (not events); "
                                 "detail pages are fetched live only", *report.warnings],
                       collected_at=report.finished_at)


FIXTURE_LOADERS: dict[str, tuple[str, Callable[[], SourceSlice]]] = {
    "official": ("03", _fixture_official),
    "luma": ("01", _fixture_luma),
    "partiful": ("01", _fixture_partiful),
    "eventbrite": ("02", _fixture_eventbrite),
    "aggregators": ("02", _fixture_aggregators),
    "discovery": ("04", _fixture_discovery),
}


def fixture_slices(names: list[str] | None = None) -> list[SourceSlice]:
    out: list[SourceSlice] = []
    for name, (window, loader) in FIXTURE_LOADERS.items():
        if names is not None and name not in names:
            continue
        started = time.perf_counter()
        try:
            got = loader()
        except Exception as exc:  # noqa: BLE001 - one broken window must not stop the run
            got = _failed(name, window, "fixture", describe(exc))
        got.duration_s = round(time.perf_counter() - started, 3)
        out.append(got)
    return out


# -- live path ------------------------------------------------------------------------


def _events_query(**extra: Any) -> DiscoveryQuery:
    base: dict[str, Any] = {
        "domain": "events", "city": "San Francisco", "start_date": WINDOW[0],
        "end_date": WINDOW[1], "limit": 1000,
    }
    base.update(extra)
    return DiscoveryQuery(**base)


async def _live_luma() -> SourceSlice:
    from conferge.events import luma

    query = _events_query(latitude=FORT_MASON[0], longitude=FORT_MASON[1], radius_km=15)
    return _from_envelope("luma", "01", "live", await luma.run(query, conference_id=None))


async def _live_partiful() -> SourceSlice:
    from conferge.events import partiful

    query = _events_query(filters={"region": "sf"})
    return _from_envelope("partiful", "01", "live", await partiful.run(query, conference_id=None))


async def _live_eventbrite() -> SourceSlice:
    from conferge.events import eventbrite

    query = _events_query(keywords=["ai", "developer", "github", "agents"])
    return _from_envelope("eventbrite", "02", "live", await eventbrite.run(query))


async def _live_aggregators() -> SourceSlice:
    from conferge.events import aggregators

    query = DiscoveryQuery(domain="events", conference_id=CONFERENCE_ID, city="San Francisco",
                           limit=1000, filters={"timezone": "America/Los_Angeles"})
    return _from_envelope("aggregators", "02", "live", await aggregators.run(query))


async def _live_official() -> SourceSlice:
    from conferge.events import official

    return _official_slice("live", await official.run({"id": CONFERENCE_ID}))


# Hand-picked demo searches, sent first through the Bright Data SERP API.
DISCOVERY_EXTRA_QUERIES = ("GitHub Universe 2026 side event",
                           "AI founders happy hour San Francisco October 28")


async def _live_discovery() -> SourceSlice:
    """Bright Data SERP -> candidate URLs -> routed detail pages -> events (window 04 pipeline).

    Without BRIGHTDATA_SERP_ZONE the SERP step reports failed and the slice carries no
    events: assembly keeps the other sources (visible fallback, nothing invented).
    """
    from conferge.api.data import load_fixture as load_api_fixture
    from conferge.core.brightdata import BrightDataClient
    from conferge.events import discovery
    from conferge.events.discovery.pipeline import run as run_discovery

    plan = discovery.fixture_plan(explicit_opt_in=True)  # query plan is configuration
    plan = plan.model_copy(update={"extra_queries": list(DISCOVERY_EXTRA_QUERIES)})
    conference = load_api_fixture().conference  # anchor id github-universe-2026
    async with BrightDataClient.from_env() as bd:
        found = await run_discovery(conference, source=discovery.SerpDiscoverySource(bd), plan=plan)
    report = found.discovery.run_report
    events = list(found.events.items)
    return SourceSlice("discovery", "04", "live", report.source_mode,
                       report.status if events or report.status == "failed" else "degraded",
                       events=events, reports=[report, *found.events.reports],
                       errors=list(dict.fromkeys([*found.discovery.errors, *found.events.errors])),
                       warnings=[f"{len(found.discovery.items)} SERP candidate URLs via brightdata:serp, "
                                 f"{len(events)} events after detail fetch",
                                 *report.warnings],
                       collected_at=report.finished_at)


LIVE_RUNNERS: dict[str, tuple[str, Callable[[], Awaitable[SourceSlice]]]] = {
    "official": ("03", _live_official),
    "luma": ("01", _live_luma),
    "partiful": ("01", _live_partiful),
    "eventbrite": ("02", _live_eventbrite),
    "aggregators": ("02", _live_aggregators),
    "discovery": ("04", _live_discovery),
}


async def live_slices(
    names: list[str] | None = None, *, timeout: float = 90.0,
    runners: dict[str, tuple[str, Callable[[], Awaitable[SourceSlice]]]] | None = None,
) -> list[SourceSlice]:
    """Every chosen runner concurrently; an exception or timeout is that source's failed slice."""
    table = runners if runners is not None else LIVE_RUNNERS
    chosen = [(n, w, r) for n, (w, r) in table.items() if names is None or n in names]
    durations: dict[str, float] = {}

    async def timed(name: str, runner: Callable[[], Awaitable[SourceSlice]]) -> SourceSlice:
        started = time.perf_counter()
        try:
            return await asyncio.wait_for(runner(), timeout)
        finally:
            durations[name] = round(time.perf_counter() - started, 3)

    results = await asyncio.gather(*(timed(n, r) for n, _, r in chosen), return_exceptions=True)
    out: list[SourceSlice] = []
    for (name, window, _), res in zip(chosen, results, strict=True):
        got = res if isinstance(res, SourceSlice) else _failed(
            name, window, "live", describe(res, timeout) if isinstance(res, BaseException)
            else f"runner returned {type(res).__name__}, not a SourceSlice")
        got.duration_s = durations.get(name)
        out.append(got)
    return out
