"""Explicit, labelled fixture access for fixtures/travel.json.

The fixture is a replay of plans captured live by `make probe-travel --write-fixture`
and relabelled `source_mode: "fixture"` on every leg. Loading requires opt-in so a
connector can never silently substitute it for a failed live collection.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from conferge.travel.models import RoutePlan

FIXTURE_PATH = Path(__file__).resolve().parents[2] / "fixtures" / "travel.json"


class FixtureNotRequested(RuntimeError):
    pass


def relabel_as_fixture(plan: RoutePlan) -> dict[str, Any]:
    data = plan.model_dump(mode="json")
    data["source_mode"] = "fixture"
    for report in data["reports"]:
        report["source_mode"] = "fixture"
    for option in data["options"]:
        for leg in option["legs"]:
            leg["source_mode"] = "fixture"
            leg["warnings"] = [*leg["warnings"], "FIXTURE: replay of a past live capture"]
            for ev in leg["evidence"]:
                ev["source_mode"] = "fixture"
    return data


def load_fixture(path: Path = FIXTURE_PATH, *, explicit_opt_in: bool = False) -> list[RoutePlan]:
    if not explicit_opt_in:
        raise FixtureNotRequested("travel fixture must be explicitly requested and labelled")
    data = json.loads(path.read_text(encoding="utf-8"))
    plans = [RoutePlan.model_validate(p) for p in data["plans"]]
    for plan in plans:
        if plan.source_mode != "fixture":
            raise ValueError("travel fixture contains a non-fixture plan")
    return plans
