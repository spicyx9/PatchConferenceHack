"""Luma public discovery adapter (window 01)."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from conferge.core.schemas import (
    DataEnvelope,
    DiscoveryQuery,
    DiscoveryResult,
    Event,
    RunReport,
    SourceRecord,
)
from conferge.events.luma._util import content_hash
from conferge.events.luma.normalize import normalize
from conferge.events.luma.source import PROVIDER, LumaError, LumaSource

__all__ = ["LumaError", "LumaSource", "load_fixture", "normalize", "run"]

FIXTURE_PATH = Path(__file__).resolve().parents[3] / "fixtures" / "luma.json"


def load_fixture(path: str | Path = FIXTURE_PATH, *, explicit_opt_in: bool = False) -> DiscoveryResult:
    """Explicit, labelled fixture load. Never called implicitly by `discover`."""
    if not explicit_opt_in:
        raise LumaError("fixture use must be explicitly requested (explicit_opt_in=True)")
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    captured = datetime.fromisoformat(raw["captured_at"])
    items = []
    for entry in raw["entries"]:
        slug = entry["event"].get("url")
        items.append(SourceRecord(
            provider=PROVIDER,
            source_id=entry["api_id"],
            source_mode="fixture",
            collected_at=captured,
            payload=entry,
            source_url=f"https://luma.com/{slug}" if slug else None,
            request_id="fixture",
            content_hash=content_hash(entry),
        ))
    report = RunReport(
        provider=PROVIDER, started_at=captured, finished_at=captured, status="ok",
        termination="not_applicable", source_mode="fixture", fetched_count=len(items),
        unique_count=len({i.source_id for i in items}), pages=0,
        warnings=[f"FIXTURE: {Path(path).name}; captured {raw['captured_at']}; not live"],
    )
    return DiscoveryResult(items=items, run_report=report)


async def run(
    query: DiscoveryQuery, *, source: LumaSource | None = None, conference_id: str | None = None,
) -> DataEnvelope[Event]:
    """Live discover + normalize. Failures surface as degraded/failed, never as fixtures."""
    own = source is None
    src = source or LumaSource()
    try:
        result = await src.discover(query)
    finally:
        if own:
            await src.aclose()
    events = [normalize(r, conference_id=conference_id) for r in result.items]
    return DataEnvelope[Event](
        items=events,
        source_mode=result.run_report.source_mode,
        status=result.run_report.status,
        reports=[result.run_report],
        errors=result.errors,
    )
