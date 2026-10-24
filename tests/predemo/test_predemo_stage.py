"""predemo: agenda size, sold-out event and replacement compared with STATUS.md."""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("predemo_check_stage", ROOT / "scripts" / "predemo_check.py")
predemo = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(predemo)

STATUS = """## Measured on abc1234 at 15:36 PDT

| Measure | Value |
|---|---|
| Agenda items (`GET /api/v1/plan`) | 32 |
| Sold-out event (labelled simulation) | Agentic engineering past the pilot |
| Replacement event | How one open source project turned funding into security at scale |
"""


def test_status_values_parsed(tmp_path: Path) -> None:
    f = tmp_path / "STATUS.md"
    f.write_text(STATUS)
    assert predemo.status_values(f) == {
        "agenda": "32", "sold_out": "Agentic engineering past the pilot",
        "replacement": "How one open source project turned funding into security at scale"}


def test_stage_rows_ok_and_fail(tmp_path: Path) -> None:
    f = tmp_path / "STATUS.md"
    f.write_text(STATUS)
    status = predemo.status_values(f)
    rows = predemo.stage_rows(32, "Agentic engineering past the pilot",
                              "How one open source project turned funding into security at scale", status)
    assert all(ok for _, ok, _ in rows)
    rows = predemo.stage_rows(31, "Other event", None, status)
    assert [ok for _, ok, _ in rows] == [False, False, False]


def test_missing_status_value_is_a_fail(tmp_path: Path) -> None:
    status = predemo.status_values(tmp_path / "absent.md")
    assert status == {"agenda": None, "sold_out": None, "replacement": None}
    rows = predemo.stage_rows(32, "x", "y", status)
    assert not any(ok for _, ok, _ in rows)
    assert all("no measured value" in detail for _, _, detail in rows)


def test_repo_status_md_has_the_three_values() -> None:
    assert None not in predemo.status_values().values()
