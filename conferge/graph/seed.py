"""Seed FalkorDB from fixtures: ``uv run python -m conferge.graph.seed``.

``fixtures/graph.json`` is a full ``GraphBundle``. Other windows' fixtures are
read best-effort: any top-level ``events``/``people``/``companies`` list whose
items validate against core schemas is ingested; anything else is skipped and
reported, never coerced. All seeded data keeps ``source_mode=fixture``.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from conferge.core.schemas import Company, Event, Person
from conferge.core.store import GraphStore, connect_graph
from conferge.graph.bundle import GraphBundle, ingest_bundle
from conferge.graph.ingest import GraphIngestor, IngestReport

FIXTURES_DIR = Path(__file__).resolve().parents[2] / "fixtures"
GRAPH_FIXTURE = FIXTURES_DIR / "graph.json"


def load_graph_fixture(path: Path = GRAPH_FIXTURE) -> GraphBundle:
    return GraphBundle.model_validate_json(path.read_text(encoding="utf-8"))


def _valid(model: Any, items: Any, warnings: list[str], label: str) -> list[Any]:
    out = []
    for index, item in enumerate(items if isinstance(items, list) else []):
        try:
            out.append(model.model_validate(item))
        except ValidationError as exc:
            warnings.append(f"{label}[{index}] skipped: {exc.error_count()} validation errors")
    return out


def seed_other_fixtures(store: GraphStore, fixtures_dir: Path = FIXTURES_DIR) -> dict[str, Any]:
    """Best-effort import of other windows' normalized fixtures (fixture mode)."""
    summary: dict[str, Any] = {}
    for path in sorted(fixtures_dir.glob("*.json")):
        if path.name == GRAPH_FIXTURE.name:
            continue
        warnings: list[str] = []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            summary[path.name] = {"status": "failed", "warnings": [str(exc)]}
            continue
        if not isinstance(data, dict):
            summary[path.name] = {"status": "skipped", "warnings": ["not an object"]}
            continue
        companies = _valid(Company, data.get("companies"), warnings, "companies")
        people = _valid(Person, data.get("people"), warnings, "people")
        events = _valid(Event, data.get("events"), warnings, "events")
        ing = GraphIngestor(store, default_mode="fixture")
        ing.ingest_companies(companies)
        ing.ingest_people(people)
        # Events from other files may reference a conference this ingestor has
        # not seen; PART_OF is then skipped and reported, not invented.
        ing.ingest_events(events)
        ing.link_participation(people)
        loaded = bool(companies or people or events)
        summary[path.name] = {
            "status": "skipped" if not loaded else "degraded" if warnings else "ok",
            "nodes": ing.report.nodes, "edges": ing.report.edges,
            "warnings": warnings + ing.report.skipped_edges,
        }
    return summary


def seed(store: GraphStore, *, include_other_fixtures: bool = False) -> dict[str, Any]:
    report: IngestReport = ingest_bundle(store, load_graph_fixture())
    result: dict[str, Any] = {
        "graph.json": {"status": "ok", "nodes": report.nodes, "edges": report.edges,
                       "warnings": report.skipped_edges + report.warnings},
    }
    if include_other_fixtures:
        result.update(seed_other_fixtures(store))
    return result


def main(argv: list[str]) -> int:
    store = connect_graph()
    print(json.dumps(seed(store, include_other_fixtures="--all" in argv), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
