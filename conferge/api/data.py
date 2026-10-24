"""Demo dataset for the API, validated against the frozen core schemas.

The repository is the injection point: window 15 (or a live runner) can pass a
``DemoData`` built from real ``DataEnvelope`` objects; by default the API loads
``fixtures/api.json`` and labels every response ``fixture``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from conferge.core.schemas import (
    Company,
    Conference,
    Event,
    FlightOffer,
    Lodging,
    Person,
)

FIXTURE_PATH = Path(__file__).resolve().parents[2] / "fixtures" / "api.json"


@dataclass
class DomainSlice:
    """Source mode and status of one domain (events, people, stays, flights)."""

    source_mode: str
    status: str
    collected_at: datetime
    warnings: list[str] = field(default_factory=list)


@dataclass
class DemoData:
    conference: Conference
    user: dict[str, Any]
    demo_goal_text: str
    events: list[Event]
    people: list[Person]
    companies: list[Company]
    stays: list[Lodging]
    flights: list[FlightOffer]
    scenarios: list[dict[str, Any]]
    domains: dict[str, DomainSlice]
    pipeline: list[dict[str, Any]] = field(default_factory=list)
    """Data pipeline rows (integration.pipeline_view), from the real RunReports of this run."""
    linkedin: dict[str, dict[str, Any]] = field(default_factory=dict)
    """person_id -> LinkedIn evidence (integration.people_linkedin.cards) shown on /people cards."""

    def event(self, event_id: str) -> Event | None:
        return next((e for e in self.events if e.id == event_id), None)

    def person(self, person_id: str) -> Person | None:
        return next((p for p in self.people if p.id == person_id), None)

    def company(self, company_id: str | None) -> Company | None:
        if company_id is None:
            return None
        return next((c for c in self.companies if c.id == company_id), None)


def load_fixture(path: Path | str = FIXTURE_PATH) -> DemoData:
    """Load and validate the w12 fixture. Every domain is labelled fixture."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    meta = raw.get("_meta", {})
    if meta.get("source_mode") != "fixture":
        raise ValueError("api fixture must declare _meta.source_mode=fixture")
    collected_at = datetime.fromisoformat(meta["collected_at"].replace("Z", "+00:00"))
    if collected_at.tzinfo is None:
        collected_at = collected_at.replace(tzinfo=timezone.utc)
    warning = f"FIXTURE: loaded from {Path(path).name}; fictional demo records, not live data"
    domains = {
        name: DomainSlice("fixture", "degraded", collected_at, [warning])
        for name in ("conference", "events", "people", "companies", "stays", "flights")
    }
    return DemoData(
        conference=Conference.model_validate(raw["conference"]),
        user=dict(raw["user"]),
        demo_goal_text=raw["demo_goal_text"],
        events=[Event.model_validate(e) for e in raw["events"]],
        people=[Person.model_validate(p) for p in raw["people"]],
        companies=[Company.model_validate(c) for c in raw["companies"]],
        stays=[Lodging.model_validate(s) for s in raw["stays"]],
        flights=[FlightOffer.model_validate(f) for f in raw["flights"]],
        scenarios=list(raw.get("scenarios", [])),
        domains=domains,
    )
