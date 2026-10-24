"""Bright Data SERP discovery, URL routing, Facebook events, conference linking (window 04).

A SERP hit is a candidate URL, never a confirmed event. Events come only from
fetched detail pages and are linked to the conference at most as `candidate`.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from conferge.core.schemas import DiscoveryResult
from conferge.events.discovery.dedupe import DedupeGroup, dedupe
from conferge.events.discovery.facebook import FacebookEventsSource
from conferge.events.discovery.link import apply_link, link_to_conference
from conferge.events.discovery.pipeline import DiscoveryRun, plan_for_conference, run
from conferge.events.discovery.queries import QueryPlan, SerpQuery, build_queries
from conferge.events.discovery.router import Route, canonicalize, route_url
from conferge.events.discovery.serp import (
    DiscoveryError,
    SerpDiscoverySource,
    parse_serp,
)

__all__ = [
    "DedupeGroup", "DiscoveryError", "DiscoveryRun", "FacebookEventsSource", "QueryPlan",
    "Route", "SerpDiscoverySource", "SerpQuery", "apply_link", "build_queries", "canonicalize",
    "dedupe", "fixture_plan", "fixture_source", "link_to_conference", "load_fixture",
    "parse_serp", "plan_for_conference", "route_url", "run",
]

FIXTURE_PATH = Path(__file__).resolve().parents[3] / "fixtures" / "discovery.json"


def _read_fixture(path: str | Path, explicit_opt_in: bool) -> dict:
    if not explicit_opt_in:
        raise DiscoveryError("fixture use must be explicitly requested (explicit_opt_in=True)")
    return json.loads(Path(path).read_text(encoding="utf-8"))


def fixture_plan(path: str | Path = FIXTURE_PATH, *, explicit_opt_in: bool = False) -> QueryPlan:
    return QueryPlan.model_validate(_read_fixture(path, explicit_opt_in)["plan"])


def fixture_source(
    path: str | Path = FIXTURE_PATH, *, explicit_opt_in: bool = False, **kwargs: object,
) -> SerpDiscoverySource:
    """A SerpDiscoverySource replaying the fixture's synthetic SERP bodies, labelled
    `source_mode="fixture"`. Queries absent from the fixture return no results."""
    raw = _read_fixture(path, explicit_opt_in)
    bodies: dict[str, str] = {
        q: json.dumps(body) for q, body in raw["serp_responses"].items()
    }

    async def replay(text: str) -> str:
        return bodies.get(text, '{"organic": []}')

    return SerpDiscoverySource(serp=replay, source_mode="fixture", **kwargs)  # type: ignore[arg-type]


async def load_fixture(
    path: str | Path = FIXTURE_PATH, *, explicit_opt_in: bool = False,
) -> DiscoveryResult:
    """Explicit, labelled fixture discovery result (never used implicitly)."""
    raw = _read_fixture(path, explicit_opt_in)
    source = fixture_source(path, explicit_opt_in=True)
    result = await source.discover_plan(QueryPlan.model_validate(raw["plan"]))
    captured = datetime.fromisoformat(raw["captured_at"])
    items = [item.model_copy(update={"collected_at": captured}) for item in result.items]
    report = result.run_report.model_copy(update={
        "warnings": [*result.run_report.warnings, f"FIXTURE: {raw['note']}"],
    })
    return DiscoveryResult(items=items, run_report=report, errors=result.errors)
