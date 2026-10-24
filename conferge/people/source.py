"""PeopleSource: core `Source` for LinkedIn profile lookup via Bright Data.

discover() resolves a supplied list of {"name", "company"} candidates to LinkedIn
profile URLs (one SERP query each). It never substitutes fixtures: with no Bright
Data credentials the run is reported as failed with no items.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from conferge.core.brightdata import BrightDataClient
from conferge.core.schemas import (
    DiscoveryQuery,
    DiscoveryResult,
    RunReport,
    SourceRecord,
    SourceRef,
)
from conferge.people.linkedin import (
    MISSING_CREDENTIALS,
    canonical_profile_url,
    fetch_profile,
    find_profile,
)
from conferge.people.models import ProfileLookup
from conferge.people.taxonomy import fold

SERP_PROVIDER = "brightdata:serp:linkedin"
MISSING_CREDENTIALS_ERROR = (
    f"{MISSING_CREDENTIALS}: BRIGHTDATA_API_KEY / BRIGHTDATA_SERP_ZONE not set"
)


class PeopleSource:
    def __init__(self, client: BrightDataClient | None = None) -> None:
        self._client = client
        self._owns_client = client is None

    @property
    def client(self) -> BrightDataClient:
        if self._client is None:
            self._client = BrightDataClient.from_env()
        return self._client

    async def __aenter__(self) -> PeopleSource:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    @staticmethod
    def _candidates(query: DiscoveryQuery) -> list[tuple[str, str | None]]:
        raw = query.filters.get("candidates") or []
        out: list[tuple[str, str | None]] = []
        for item in raw if isinstance(raw, list) else []:
            if not isinstance(item, dict):
                continue
            name = item.get("name")
            if not isinstance(name, str) or not name.strip():
                continue
            company = item.get("company")
            company = company.strip() if isinstance(company, str) and company.strip() else None
            out.append((name.strip(), company))
        return out

    @staticmethod
    def _record(lookup: ProfileLookup) -> SourceRecord:
        return SourceRecord(
            provider=SERP_PROVIDER,
            source_id=f"{fold(lookup.name)}|{fold(lookup.company or '')}",
            source_mode="live",
            collected_at=lookup.collected_at,
            payload=lookup.model_dump(mode="json"),
            source_url=lookup.linkedin_url,
        )

    def _report(
        self, started: datetime, *, status: Any, termination: Any, items: list[SourceRecord],
        expected: int, errors: list[str], warnings: list[str],
    ) -> RunReport:
        return RunReport(
            provider=SERP_PROVIDER, started_at=started,
            finished_at=datetime.now(timezone.utc), status=status, termination=termination,
            source_mode="live", fetched_count=len(items),
            unique_count=len({i.source_id for i in items}), pages=len(items),
            expected_count=expected, errors=errors, warnings=warnings,
        )

    async def discover(self, query: DiscoveryQuery) -> DiscoveryResult:
        if query.domain != "people":
            raise ValueError("PeopleSource only handles domain='people'")
        started = datetime.now(timezone.utc)
        candidates = self._candidates(query)
        if not candidates:
            errors = ["no candidates supplied"]
            report = self._report(started, status="failed", termination="error", items=[],
                                  expected=0, errors=errors, warnings=[])
            return DiscoveryResult(items=[], run_report=report, errors=errors)

        warnings: list[str] = []
        if len(candidates) > query.limit:
            warnings.append(f"candidates capped at limit={query.limit} of {len(candidates)}")
        selected = candidates[: query.limit]

        lookups = [await find_profile(self.client, name, company) for name, company in selected]
        if all(lk.status == "failed" and (lk.error or "").startswith(MISSING_CREDENTIALS)
               for lk in lookups):
            errors = [MISSING_CREDENTIALS_ERROR]
            report = self._report(started, status="failed", termination="error", items=[],
                                  expected=len(selected), errors=errors, warnings=warnings)
            return DiscoveryResult(items=[], run_report=report, errors=errors)

        items = [self._record(lk) for lk in lookups]
        errors = sorted({f"{lk.name}: {lk.error}" for lk in lookups if lk.status == "failed"})
        warnings.extend(f"{lk.name}: {lk.error}" for lk in lookups if lk.status == "degraded")
        statuses = {lk.status for lk in lookups}
        if statuses == {"ok"}:
            status, termination = "ok", "exhausted"
        elif statuses == {"failed"}:
            status, termination = "failed", "error"
        else:
            status = "degraded"
            termination = "error" if "failed" in statuses else "exhausted"
        report = self._report(started, status=status, termination=termination, items=items,
                              expected=len(selected), errors=errors, warnings=warnings)
        return DiscoveryResult(items=items, run_report=report, errors=errors)

    async def fetch_details(self, ref: SourceRef) -> SourceRecord:
        url = canonical_profile_url(str(ref.url)) if ref.url else None
        if url is None:
            raise ValueError("fetch_details needs a linkedin.com/in/ profile URL")
        return await fetch_profile(self.client, url)
