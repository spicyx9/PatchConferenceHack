"""Lodging window (w05): Booking, Google Hotels, Airbnb stays with price-truth rules.

Entry points:
- ``LodgingSource``: core ``Source`` contract over the three providers (raw records);
- ``run(query)``: discover + verify + normalize + distance + dedup -> ``DataEnvelope[Lodging]``;
- ``load_fixture`` / ``fixture_envelope``: explicit, labelled fixture (never implicit).
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from conferge.core.schemas import (
    DataEnvelope,
    DiscoveryQuery,
    DiscoveryResult,
    Lodging,
    SourceRecord,
    SourceRef,
)
from conferge.lodging._common import content_hash, now_utc, report, worst_status
from conferge.lodging.models import LodgingQuery, Place
from conferge.lodging.normalize import normalize
from conferge.lodging.service import LodgingSearch, LodgingService, run

__all__ = [
    "FIXTURE_PATH",
    "LodgingError", "LodgingQuery", "LodgingSearch", "LodgingService", "LodgingSource", "Place",
    "fixture_envelope", "load_fixture", "normalize", "run",
]

PROVIDER = "lodging"
FIXTURE_PATH = Path(__file__).resolve().parents[2] / "fixtures" / "lodging.json"


class LodgingError(RuntimeError):
    pass


class LodgingSource:
    """Aggregate Source: raw provider records, no normalization (see ``run``)."""

    def __init__(self, sources: dict[str, Any] | None = None, *,
                 clock: Callable[[], datetime] = now_utc) -> None:
        if sources is None:
            from conferge.lodging.service import default_sources

            sources = default_sources()
        self._sources = sources
        self._clock = clock

    async def aclose(self) -> None:
        for src in self._sources.values():
            close = getattr(src, "aclose", None)
            if close is not None:
                await close()

    async def discover(self, query: DiscoveryQuery) -> DiscoveryResult:
        started = self._clock()
        try:
            q = LodgingQuery.from_discovery(query)
        except ValueError as exc:
            rep = report(PROVIDER, started, status="failed", termination="error",
                         errors=[f"invalid lodging query: {exc}"[:300]])
            return DiscoveryResult(run_report=rep, errors=list(rep.errors))
        names = list(self._sources)
        results = await asyncio.gather(*(self._sources[n].search(q) for n in names),
                                       return_exceptions=True)
        items: list[SourceRecord] = []
        errors: list[str] = []
        warnings: list[str] = []
        statuses = []
        terminations = []
        fetched = unique = pages = 0
        for name, res in zip(names, results, strict=True):
            if isinstance(res, BaseException):
                statuses.append("failed")
                terminations.append("error")
                errors.append(f"{name}: {type(res).__name__}: {str(res)[:200]}")
                continue
            rep = res.run_report
            statuses.append(rep.status)
            terminations.append(rep.termination)
            items.extend(res.items)
            fetched += rep.fetched_count
            unique += rep.unique_count
            pages += rep.pages
            errors.extend(f"{name}: {e}" for e in rep.errors)
            warnings.extend(f"{name}: {w}" for w in rep.warnings)
            warnings.append(f"{name}: {rep.status}/{rep.termination} ({rep.source_mode})")
        status = worst_status(statuses)
        bad = [t for t in terminations if t not in {"exhausted", "not_applicable"}]
        modes = {i.source_mode for i in items}
        rep = report(
            PROVIDER, started, status=status, termination=bad[0] if bad else "exhausted",
            source_mode=modes.pop() if len(modes) == 1 else "live",
            fetched=fetched, unique=unique, pages=pages, errors=errors, warnings=warnings,
        )
        return DiscoveryResult(items=items, run_report=rep, errors=errors)

    async def fetch_details(self, ref: SourceRef) -> SourceRecord:
        src = self._sources.get(ref.provider)
        if src is None:
            raise LodgingError(f"unknown lodging provider {ref.provider!r}")
        return await src.fetch_details(ref)


def _fixture_raw(path: str | Path, explicit_opt_in: bool) -> dict[str, Any]:
    if not explicit_opt_in:
        raise LodgingError("fixture use must be explicitly requested (explicit_opt_in=True)")
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_fixture(path: str | Path = FIXTURE_PATH, *, explicit_opt_in: bool = False) -> DiscoveryResult:
    """Explicit, labelled fixture load. Never called implicitly by ``discover`` or ``run``."""
    raw = _fixture_raw(path, explicit_opt_in)
    captured = datetime.fromisoformat(raw["captured_at"])
    items = [
        SourceRecord(
            provider=r["provider"], source_id=r["source_id"], source_mode="fixture",
            collected_at=datetime.fromisoformat(r.get("collected_at") or raw["captured_at"]),
            payload=r["payload"], source_url=r.get("source_url"), request_id="fixture",
            content_hash=content_hash(r["payload"]),
        )
        for r in raw["records"]
    ]
    rep = report(
        PROVIDER, captured, status="ok", termination="not_applicable", source_mode="fixture",
        fetched=len(items), unique=len({(i.provider, i.source_id) for i in items}),
        finished_at=captured,
        warnings=[f"FIXTURE: {Path(path).name}; captured {raw['captured_at']}; not live. "
                  f"{raw.get('notice', '')}".strip()],
    )
    return DiscoveryResult(items=items, run_report=rep)


def fixture_query(path: str | Path = FIXTURE_PATH, *, explicit_opt_in: bool = False) -> LodgingQuery:
    return LodgingQuery.model_validate(_fixture_raw(path, explicit_opt_in)["query"])


def fixture_envelope(
    path: str | Path = FIXTURE_PATH, *, explicit_opt_in: bool = False,
    clock: Callable[[], datetime] = now_utc,
) -> DataEnvelope[Lodging]:
    """Normalized fixture stays, every item ``source_mode=fixture`` in its evidence."""
    result = load_fixture(path, explicit_opt_in=explicit_opt_in)
    q = fixture_query(path, explicit_opt_in=explicit_opt_in)
    search = LodgingService(sources={}, clock=clock).assemble(
        list(result.items), q, [result.run_report])
    return search.envelope
