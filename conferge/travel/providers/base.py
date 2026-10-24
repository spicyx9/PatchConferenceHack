"""Pluggable route-provider interface and shared run-report helpers."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable

from conferge.core.schemas import RunReport, RunStatus, SourceMode, Termination
from conferge.travel.models import Mode, Place, ProviderOutcome, utcnow


@runtime_checkable
class RouteProvider(Protocol):
    """A source of route legs. Must never invent a time or a price."""

    name: str
    modes: frozenset[Mode]

    async def route(
        self, origin: Place, destination: Place, *, mode: Mode,
        depart_at: datetime | None = None,
    ) -> ProviderOutcome: ...


def report(
    provider: str, started_at: datetime, *, status: RunStatus, termination: Termination,
    source_mode: SourceMode = "live", fetched: int = 0, unique: int | None = None,
    pages: int = 0, errors: list[str] | None = None, warnings: list[str] | None = None,
) -> RunReport:
    return RunReport(
        provider=provider, started_at=started_at, finished_at=utcnow(), status=status,
        termination=termination, source_mode=source_mode, fetched_count=fetched,
        unique_count=fetched if unique is None else unique, pages=pages,
        errors=errors or [], warnings=warnings or [],
    )


def failed(
    provider: str, started_at: datetime, error: str, *,
    termination: Termination = "error",
) -> ProviderOutcome:
    """Visible failure: no legs, status failed, message kept."""
    return ProviderOutcome(
        legs=[], run_report=report(
            provider, started_at, status="failed", termination=termination, errors=[error],
        ),
    )
