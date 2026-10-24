"""docs/submission/FORM.md: form limits hold, and only the agreed number placeholders are used."""

from __future__ import annotations

import re
from pathlib import Path

FORM = Path(__file__).resolve().parents[2] / "docs" / "submission" / "FORM.md"
PLACEHOLDERS = {"EVENTS", "AGENDA", "NODES", "EDGES", "TESTS", "LINKEDIN", "STAYS", "FLIGHTS"}


def _section(name: str) -> str:
    text = FORM.read_text(encoding="utf-8")
    return text.split(f"## {name}\n", 1)[1].split("\n## ", 1)[0].strip()


def test_tagline_and_description_limits() -> None:
    assert len(_section("One-line tagline")) <= 100
    assert len(_section("Description").split()) <= 200


def test_only_known_placeholders() -> None:
    used = set(re.findall(r"\{\{(\w+)\}\}", FORM.read_text(encoding="utf-8")))
    assert used <= PLACEHOLDERS
