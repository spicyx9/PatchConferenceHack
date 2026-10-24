"""Loader for ``fixtures/antifomo.json`` (synthetic, labelled ``fixture``)."""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from conferge.core.schemas import Conference, Event, Goal, Person

FIXTURE_PATH = Path(__file__).resolve().parents[3] / "fixtures" / "antifomo.json"
PROVIDER = "fixture:w10-antifomo"


class PlanningFixture(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)
    conference: Conference
    goals: list[Goal]
    people: list[Person]
    events: list[Event]
    venues: dict[str, dict[str, Any]] = Field(default_factory=dict)
    scenarios: list[dict[str, Any]] = Field(default_factory=list)
    collected_at: datetime


def _evidence(collected_at: str) -> list[dict[str, Any]]:
    return [{"provider": PROVIDER, "source_mode": "fixture", "collected_at": collected_at,
             "raw_ref": "fixtures/antifomo.json"}]


def resolve_event(raw: dict[str, Any], venues: dict[str, dict[str, Any]], collected_at: str
                  ) -> Event:
    data = deepcopy(raw)
    if isinstance(data.get("venue"), str):
        data["venue"] = venues[data["venue"]]
    data.setdefault("evidence", _evidence(collected_at))
    return Event.model_validate(data)


def load_fixture(path: Path | None = None) -> PlanningFixture:
    target = path or FIXTURE_PATH
    if not target.exists():
        raise FileNotFoundError(f"planning fixture missing: {target}")
    raw = json.loads(target.read_text())
    meta = raw["_meta"]
    if meta.get("source_mode") != "fixture":
        raise ValueError("fixtures/antifomo.json must be labelled source_mode=fixture")
    at = meta["collected_at"]
    venues = raw["venues"]
    people = []
    for p in raw["people"]:
        people.append(Person.model_validate({**p, "evidence": p.get("evidence") or _evidence(at)}))
    return PlanningFixture(
        conference=Conference.model_validate(raw["conference"]),
        goals=[Goal.model_validate(g) for g in raw["goals"]],
        people=people,
        events=[resolve_event(e, venues, at) for e in raw["events"]],
        venues=venues,
        scenarios=raw.get("scenarios", []),
        collected_at=datetime.fromisoformat(at),
    )


__all__ = ["FIXTURE_PATH", "PlanningFixture", "load_fixture", "resolve_event"]
