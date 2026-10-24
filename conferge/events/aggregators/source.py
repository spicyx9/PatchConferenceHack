"""Conference-party aggregator sources implementing the core Source protocol.

Site: conferenceparties.com/<slug>/ (raidandev and reinventradar were removed:
Las Vegas re:Invent only, nothing for the anchor conference). Pages are public, fetched with httpx; when the
site blocks us and a Bright Data client with an unlocker zone is configured,
the page is retried through Web Unlocker. Failures return degraded/failed
reports; fixtures are never substituted here.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

import httpx

from conferge.core.brightdata import BrightDataClient, BrightDataError
from conferge.core.schemas import (
    DataEnvelope,
    DiscoveryQuery,
    DiscoveryResult,
    Event,
    RunReport,
    SourceRecord,
    SourceRef,
)
from conferge.events.aggregators import conferenceparties
from conferge.events.aggregators.common import (
    BROWSER_UA,
    ParseOutcome,
    build_report,
    termination_for_status,
)
from conferge.events.aggregators.normalize import normalize_records

Site = Literal["conferenceparties"]
FIXTURE_PATH = Path(__file__).resolve().parents[3] / "fixtures" / "eventbrite-aggregators.json"

# Default listing pages for the demo anchor conference.
DEFAULT_TARGETS: dict[str, list[dict[str, str]]] = {
    "github-universe-2026": [{"site": "conferenceparties", "slug": "github26"}],
}


def _url_for(site: Site, slug: str) -> str:
    return conferenceparties.page_url(slug)


def _parse(site: Site, html: str, slug: str, collected_at: datetime, url: str) -> ParseOutcome:
    return conferenceparties.parse_page(
        html, slug=slug, collected_at=collected_at, source_mode="live", url=url
    )


class AggregatorSource:
    """One aggregator page (site + slug). discover() fetches and parses it once."""

    def __init__(
        self, site: Site, slug: str, *, client: httpx.AsyncClient | None = None,
        brightdata: BrightDataClient | None = None, timeout: float = 30.0,
    ) -> None:
        if site != "conferenceparties":
            raise ValueError(f"unknown aggregator site: {site}")
        self.site: Site = site
        self.slug = slug
        self.url = _url_for(site, slug)
        self._client = client
        self._brightdata = brightdata
        self._timeout = timeout

    async def _get(self) -> tuple[str | None, int | None, str | None]:
        """Return (html, status_code, error). Never raises for network problems."""
        owns = self._client is None
        client = self._client or httpx.AsyncClient(
            timeout=self._timeout, follow_redirects=True,
            headers={"User-Agent": BROWSER_UA, "Accept": "text/html,application/xhtml+xml"},
        )
        try:
            response = await client.get(self.url)
            if response.status_code >= 400:
                return None, response.status_code, f"HTTP {response.status_code} for {self.url}"
            return response.text, response.status_code, None
        except httpx.HTTPError as exc:
            return None, None, f"network error for {self.url}: {exc.__class__.__name__}"
        finally:
            if owns:
                await client.aclose()

    async def _unlock(self) -> str | None:
        if self._brightdata is None or not self._brightdata.unlocker_zone:
            return None
        try:
            return await self._brightdata.unlock(self.url)
        except BrightDataError:
            return None

    async def discover(self, query: DiscoveryQuery) -> DiscoveryResult:
        started_at = datetime.now(timezone.utc)
        html, status_code, error = await self._get()
        warnings: list[str] = []
        if html is None and status_code in {401, 403, 429}:
            unlocked = await self._unlock()
            if unlocked is not None:
                html, error = unlocked, None
                warnings.append("fetched via Bright Data Web Unlocker after direct block")
        if html is None:
            outcome = ParseOutcome(
                termination=termination_for_status(status_code) if status_code else "error",
                errors=[error or "unknown fetch error"],
            )
        else:
            outcome = _parse(self.site, html, self.slug, datetime.now(timezone.utc), self.url)
        outcome.warnings = warnings + outcome.warnings
        records = outcome.records[: query.limit] if query.limit else outcome.records
        if len(records) < len(outcome.records):
            outcome.warnings.append(f"limit_reached:{query.limit} of {len(outcome.records)}")
            outcome.termination = "page_cap"
        outcome.records = records
        # An explicit empty list (header present, zero rows) is a valid exhausted read.
        report = build_report(
            self.site, started_at, outcome, source_mode="live", pages=1 if html else 0,
            ok_on_empty="empty_page" in outcome.warnings,
        )
        return DiscoveryResult(items=records, run_report=report, errors=list(outcome.errors))

    async def fetch_details(self, ref: SourceRef) -> SourceRecord:
        """Aggregator rows have no detail page of their own: re-read the listing row."""
        result = await self.discover(DiscoveryQuery(domain="events", limit=1000))
        for record in result.items:
            if record.source_id == ref.source_id:
                return record
        raise LookupError(
            f"{self.site} row {ref.source_id} not found ({result.run_report.termination})"
        )


def targets_for(query: DiscoveryQuery) -> list[dict[str, str]]:
    explicit = query.filters.get("aggregators")
    if isinstance(explicit, list) and explicit:
        return [dict(item) for item in explicit]
    return list(DEFAULT_TARGETS.get(query.conference_id or "", []))


def _envelope_status(reports: list[RunReport]) -> Literal["ok", "degraded", "failed"]:
    if not reports or all(report.status == "failed" for report in reports):
        return "failed"
    if all(report.status == "ok" for report in reports):
        return "ok"
    return "degraded"


async def run(
    query: DiscoveryQuery, *,
    source_factory: Callable[[Site, str], AggregatorSource] | None = None,
) -> DataEnvelope[Event]:
    """Discover every configured aggregator page and normalize to Event (live only)."""
    factory = source_factory or (lambda site, slug: AggregatorSource(site, slug))
    targets = targets_for(query)
    if not targets:
        return DataEnvelope[Event](
            source_mode="live", status="failed",
            errors=["no aggregator targets: pass filters.aggregators=[{site, slug}]"],
        )
    results = await asyncio.gather(*(
        factory(target["site"], target.get("slug", "")).discover(query)  # type: ignore[arg-type]
        for target in targets
    ))
    events: list[Event] = []
    errors: list[str] = []
    for result in results:
        normalized, norm_errors = normalize_records(
            result.items, conference_id=query.conference_id,
            timezone_name=query.filters.get("timezone"), city=query.city,
        )
        events.extend(normalized)
        errors.extend(result.errors + norm_errors)
    reports = [result.run_report for result in results]
    return DataEnvelope[Event](
        items=events, source_mode="live", status=_envelope_status(reports),
        reports=reports, errors=errors,
    )


def load_fixture(path: str | Path = FIXTURE_PATH, *, explicit_opt_in: bool = False) -> DiscoveryResult:
    """Labelled fixture replay as a DiscoveryResult, like the luma, partiful and discovery loaders."""
    if not explicit_opt_in:
        raise RuntimeError("fixture use must be explicitly enabled and labelled")
    data: dict[str, Any] = json.loads(Path(path).read_text(encoding="utf-8"))
    records = [SourceRecord.model_validate(item) for item in data.get("aggregators", [])]
    if any(record.source_mode != "fixture" for record in records):
        raise ValueError("fixture file contains records not labelled source_mode=fixture")
    captured = datetime.fromisoformat(data["captured_at"])
    report = RunReport(
        provider="aggregators", started_at=captured, finished_at=captured, status="ok",
        termination="not_applicable", source_mode="fixture", fetched_count=len(records),
        unique_count=len({r.source_id for r in records}), pages=0,
        warnings=[f"FIXTURE: {Path(path).name}; captured {data['captured_at']}; not live"],
    )
    return DiscoveryResult(items=records, run_report=report)


def load_fixture_records(*, explicit_opt_in: bool = False) -> list[SourceRecord]:
    """Backward-compatible alias: the records of `load_fixture`."""
    return load_fixture(FIXTURE_PATH, explicit_opt_in=explicit_opt_in).items
