"""OfficialConferenceSource: GitHub Universe 2026 official program, speakers and sponsors.

discover() returns raw RainFocus items as SourceRecord (payload preserved); collect()
adds the normalization to core models wrapped in DataEnvelope. Failures are reported
with status degraded/failed. No fixture is ever substituted here; load_fixture() is a
separate, explicit call whose output is labelled source_mode="fixture".
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from conferge.core.schemas import (
    Company,
    Conference,
    DataEnvelope,
    DiscoveryQuery,
    DiscoveryResult,
    Event,
    Person,
    RunReport,
    RunStatus,
    SourceMode,
    SourceRecord,
    SourceRef,
)
from conferge.events.official.normalize import (
    CONFERENCE_ID,
    PROVIDER,
    OfficialCatalog,
    normalize_catalog,
)
from conferge.events.official.rainfocus import (
    CATALOG_URL,
    SPONSOR_URL,
    Kind,
    RainFocusClient,
    SearchRun,
)

_SUPPORTED_DOMAINS = {"events", "conference", "people"}
_KIND_URL = {"session": CATALOG_URL, "exhibitor": SPONSOR_URL}
_ID_FIELD = {"session": "sessionID", "exhibitor": "exhibitorID"}
FIXTURE_PATH = Path(__file__).resolve().parents[3] / "fixtures" / "official.json"


def content_hash(payload: dict[str, Any]) -> str:
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _status(runs: list[SearchRun]) -> RunStatus:
    if all(r.complete for r in runs):
        return "ok"
    if any(r.items for r in runs):
        return "degraded"
    return "failed"


@dataclass
class OfficialCollection:
    """Normalized output of one collection; every envelope carries mode and reports."""

    conference: Conference | None
    events: DataEnvelope[Event]
    people: DataEnvelope[Person]
    companies: DataEnvelope[Company]
    discovery: DiscoveryResult | None = None
    warnings: list[str] = field(default_factory=list)

    @property
    def source_mode(self) -> SourceMode:
        return self.events.source_mode  # type: ignore[return-value]

    @property
    def status(self) -> RunStatus:
        return self.events.status


class OfficialConferenceSource:
    """Implements conferge.core.contracts.Source for the official Universe catalog."""

    provider = PROVIDER

    def __init__(
        self,
        client: RainFocusClient | None = None,
        *,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._client = client or RainFocusClient(http_client)
        self._owns_client = client is None

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def __aenter__(self) -> OfficialConferenceSource:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    @staticmethod
    def _records(run: SearchRun, collected_at: datetime) -> list[SourceRecord]:
        records = []
        for item in run.items:
            source_id = f"{run.kind}:{item[_ID_FIELD[run.kind]]}"
            records.append(SourceRecord(
                provider=PROVIDER, source_id=source_id, source_mode="live",
                collected_at=collected_at, payload=item, source_url=_KIND_URL[run.kind],
                content_hash=content_hash(item),
            ))
        return records

    async def _run_kinds(
        self, kinds: list[Kind], limit: int | None
    ) -> tuple[list[SearchRun], datetime, datetime]:
        started = datetime.now(timezone.utc)
        runs = [await self._client.search(kind, limit=limit) for kind in kinds]
        return runs, started, datetime.now(timezone.utc)

    async def discover(self, query: DiscoveryQuery) -> DiscoveryResult:
        if query.conference_id not in (None, CONFERENCE_ID):
            now = datetime.now(timezone.utc)
            return DiscoveryResult(run_report=RunReport(
                provider=PROVIDER, started_at=now, finished_at=now, status="ok",
                termination="not_applicable", source_mode="live", fetched_count=0,
                unique_count=0, warnings=[f"conference {query.conference_id} not covered"],
            ))
        if query.domain not in _SUPPORTED_DOMAINS:
            now = datetime.now(timezone.utc)
            return DiscoveryResult(run_report=RunReport(
                provider=PROVIDER, started_at=now, finished_at=now, status="ok",
                termination="not_applicable", source_mode="live", fetched_count=0,
                unique_count=0, warnings=[f"domain {query.domain} not served by official"],
            ))
        kinds: list[Kind] = ["session", "exhibitor"]
        runs, started, finished = await self._run_kinds(kinds, query.limit)
        items: list[SourceRecord] = []
        for run in runs:
            items += self._records(run, finished)
        errors = [e for r in runs for e in r.errors]
        warnings = [w for r in runs for w in r.warnings]
        status = _status(runs)
        termination = "exhausted" if status == "ok" else next(
            r.termination for r in runs if not r.complete
        )
        expected = None
        if all(r.expected_count is not None for r in runs):
            expected = sum(r.expected_count or 0 for r in runs)
        if status == "ok" and expected is not None and len(items) < expected:
            status, termination = "degraded", "cursor_stuck"
            warnings.append(f"collected {len(items)} of declared {expected}")
        report = RunReport(
            provider=PROVIDER, started_at=started, finished_at=finished, status=status,
            termination=termination, source_mode="live",
            fetched_count=max(sum(r.fetched_count for r in runs), len(items)),
            unique_count=len(items), pages=sum(r.pages for r in runs),
            expected_count=expected, errors=errors,
            warnings=warnings + [f"{r.kind}: {r.termination}, {len(r.items)} items"
                                 for r in runs],
        )
        return DiscoveryResult(items=items, run_report=report, errors=errors)

    async def fetch_details(self, ref: SourceRef) -> SourceRecord:
        """Re-reads the public catalog and returns the matching raw record."""
        kind, _, raw_id = ref.source_id.partition(":")
        if kind not in _ID_FIELD or not raw_id:
            raise ValueError(f"unsupported source_id {ref.source_id!r}")
        run = await self._client.search(kind)  # type: ignore[arg-type]
        if run.errors and not run.items:
            raise LookupError(f"{ref.source_id}: catalog unavailable ({run.termination})")
        collected_at = datetime.now(timezone.utc)
        for record in self._records(run, collected_at):
            if record.source_id == ref.source_id:
                return record
        raise LookupError(f"{ref.source_id}: not found in public catalog")

    async def collect(self, query: DiscoveryQuery | None = None) -> OfficialCollection:
        query = query or DiscoveryQuery(domain="conference", conference_id=CONFERENCE_ID,
                                        limit=1000)
        result = await self.discover(query)
        sessions = [r.payload for r in result.items if r.source_id.startswith("session:")]
        exhibitors = [r.payload for r in result.items if r.source_id.startswith("exhibitor:")]
        collected_at = result.run_report.finished_at
        catalog = normalize_catalog(sessions, exhibitors, collected_at=collected_at,
                                    source_mode="live")
        return _wrap(catalog, result.run_report, result.errors, discovery=result,
                     have_data=bool(result.items))


def _wrap(
    catalog: OfficialCatalog, report: RunReport, errors: list[str], *,
    discovery: DiscoveryResult | None, have_data: bool,
) -> OfficialCollection:
    mode = report.source_mode
    status = report.status
    common: dict[str, Any] = {"source_mode": mode, "status": status,
                              "collected_at": report.finished_at, "reports": [report],
                              "errors": errors}
    return OfficialCollection(
        conference=catalog.conference if have_data else None,
        events=DataEnvelope[Event](items=catalog.events, **common),
        people=DataEnvelope[Person](items=catalog.people, **common),
        companies=DataEnvelope[Company](items=catalog.companies, **common),
        discovery=discovery,
        warnings=catalog.warnings,
    )


def load_fixture(path: str | Path = FIXTURE_PATH, *, explicit_opt_in: bool = False
                 ) -> OfficialCollection:
    """Explicit, labelled fixture: a real public catalog capture replayed offline.

    Records are re-normalized with source_mode="fixture"; they are never reported live.
    """
    if not explicit_opt_in:
        raise RuntimeError("Fixture use must be explicitly enabled and labelled")
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if data.get("source_mode") != "fixture":
        raise ValueError("official fixture must declare source_mode='fixture'")
    captured_at = datetime.fromisoformat(data["captured_at"])
    raw = data.get("raw") or {}
    catalog = normalize_catalog(raw.get("sessions") or [], raw.get("exhibitors") or [],
                                collected_at=captured_at, source_mode="fixture")
    now = datetime.now(timezone.utc)
    report = RunReport(
        provider=PROVIDER, started_at=now, finished_at=now, status="ok",
        termination="not_applicable", source_mode="fixture",
        fetched_count=len(raw.get("sessions") or []) + len(raw.get("exhibitors") or []),
        unique_count=len(raw.get("sessions") or []) + len(raw.get("exhibitors") or []),
        warnings=[f"FIXTURE: replay of public catalog captured at {data['captured_at']}; "
                  "not a live response"],
    )
    return _wrap(catalog, report, [], discovery=None, have_data=True)


async def run(conference: dict[str, Any] | None = None, *,
              http_client: httpx.AsyncClient | None = None) -> OfficialCollection:
    """Entry point used by probes and integration: live collection, no silent fallback."""
    conference_id = (conference or {}).get("id", CONFERENCE_ID)
    query = DiscoveryQuery(domain="conference", conference_id=conference_id, limit=1000)
    async with OfficialConferenceSource(http_client=http_client) as source:
        return await source.collect(query)
