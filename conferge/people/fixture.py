"""Explicit fixture for window 07: `fixtures/people.json`.

Derived deterministically from the w03 official catalog fixture and the w01 Luma fixture
(both real public captures replayed offline). No person is invented: every profile is a
published speaker or a public Luma host. Regenerate with `python -m conferge.people.fixture`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from conferge.people.collect import collect_fixtures
from conferge.people.dedup import dedupe
from conferge.people.models import PersonProfile

FIXTURE_PATH = Path(__file__).resolve().parents[2] / "fixtures" / "people.json"
LABEL = ("FIXTURE: people derived offline from fixtures/official.json (public GitHub Universe "
         "2026 catalog speakers) and fixtures/luma.json (public Luma hosts). Not live. "
         "No private guest list. Re-run make probe-people for live enrichment.")


def build_fixture() -> dict[str, Any]:
    collected = collect_fixtures(explicit_opt_in=True)
    profiles, ambiguities = dedupe(collected.profiles)
    captured = sorted({str(r.finished_at.isoformat()) for r in collected.reports})
    return {
        "source_mode": "fixture",
        "label": LABEL,
        "derived_from": ["fixtures/official.json", "fixtures/luma.json"],
        "source_reports_finished_at": captured,
        "counts": {
            "profiles": len(profiles),
            "speakers": sum(any(p.kind == "speaker" for p in x.presences) for x in profiles),
            "hosts": sum(any(p.kind == "host" for p in x.presences) for x in profiles),
            "ambiguous_pairs": len(ambiguities),
        },
        "ambiguities": [a.__dict__ for a in ambiguities],
        # Bios stay in fixtures/official.json; topics derived from them are kept here.
        "profiles": [p.model_dump(mode="json", exclude_none=True,
                                  exclude={"person": {"bio"}}) for p in profiles],
    }


def load_fixture(path: str | Path = FIXTURE_PATH, *, explicit_opt_in: bool = False
                 ) -> list[PersonProfile]:
    if not explicit_opt_in:
        raise RuntimeError("fixture use must be explicitly requested (explicit_opt_in=True)")
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if data.get("source_mode") != "fixture":
        raise ValueError("people fixture must declare source_mode='fixture'")
    profiles = [PersonProfile.model_validate(p) for p in data["profiles"]]
    for profile in profiles:
        if any(e.source_mode != "fixture" for e in profile.person.evidence):
            raise ValueError(f"{profile.id}: fixture evidence must be source_mode='fixture'")
    return profiles


def write_fixture(path: str | Path = FIXTURE_PATH) -> Path:
    path = Path(path)
    path.write_text(json.dumps(build_fixture(), indent=None, ensure_ascii=False,
                               separators=(",", ":")) + "\n",
                    encoding="utf-8")
    return path


if __name__ == "__main__":
    print(write_fixture())
