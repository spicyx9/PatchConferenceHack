from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

from conferge.integration import pipeline, render_markdown, run_e2e
from conferge.integration.sources import SourceSlice, fixture_slices

EXPECTED_STAGES = [
    "inventory", "sources", "check:provenance", "check:labels", "check:relations",
    "check:dedup", "planning", "graph", "travel", "api", "demo-backup:w13-replay",
    "demo-backup:api-fixture",
]


@pytest.fixture(scope="module")
def fixture_report() -> pipeline.E2EReport:
    return asyncio.run(run_e2e("fixture"))


def test_fixture_e2e_passes_offline(no_network: None) -> None:
    report = asyncio.run(run_e2e("fixture", include_backup=False))
    assert report.passed, [(s.name, s.findings[:3]) for s in report.stages if s.outcome == "fail"]


def test_fixture_e2e_runs_every_stage(fixture_report: pipeline.E2EReport) -> None:
    assert [s.name for s in fixture_report.stages] == EXPECTED_STAGES
    assert fixture_report.passed
    assert fixture_report.data_mode == "fixture"
    for name in ("check:provenance", "check:labels", "check:relations", "travel", "api",
                 "demo-backup:w13-replay", "demo-backup:api-fixture"):
        assert fixture_report.stage(name).outcome == "pass", fixture_report.stage(name).findings


def test_graph_stage_goes_through_graphstore_only(fixture_report: pipeline.E2EReport) -> None:
    graph = fixture_report.stage("graph")
    assert graph.outcome in {"pass", "warn"}
    assert not any("non-GraphStore" in f for f in graph.findings)
    nodes = graph.data["nodes"]
    assert nodes["Conference"] == 1
    assert nodes["Event"] > 100 and nodes["Person"] > 100
    assert graph.data["edges"].get("SPEAKS_AT", 0) > 0


def test_planning_never_claims_live_on_fixture(fixture_report: pipeline.E2EReport) -> None:
    planning = fixture_report.stage("planning")
    assert planning.outcome == "pass", planning.findings
    assert "source_mode=fixture" in planning.detail
    assert planning.data["top"]


def test_live_failure_without_fallback_is_failed_not_fixture(
    monkeypatch: pytest.MonkeyPatch, no_network: None,
) -> None:
    async def all_failed(names=None, *, timeout=90.0, runners=None):  # noqa: ANN001
        return [SourceSlice("luma", "01", "live", "live", "failed", errors=["HTTP 403"])]

    monkeypatch.setattr(pipeline, "live_slices", all_failed)
    report = asyncio.run(run_e2e("live", include_backup=False, sources=["luma"]))
    assert report.stage("sources").outcome == "fail"
    assert [s.source_mode for s in report.slices] == ["live"]
    assert not report.passed


def test_live_failure_with_explicit_fallback_is_labelled_fixture(
    monkeypatch: pytest.MonkeyPatch, no_network: None,
) -> None:
    async def all_failed(names=None, *, timeout=90.0, runners=None):  # noqa: ANN001
        return [SourceSlice("official", "03", "live", "live", "failed", errors=["timeout"])]

    monkeypatch.setattr(pipeline, "live_slices", all_failed)
    report = asyncio.run(run_e2e("live", fallback_fixture=True, include_backup=False,
                                 sources=["official"]))
    modes = [(s.attempted, s.source_mode, s.status) for s in report.slices]
    assert modes[0] == ("live", "live", "failed")
    assert modes[1][:2] == ("fixture", "fixture")
    assert "explicit fixture fallback" in report.slices[1].warnings[0]
    assert report.data_mode == "fixture"
    assert report.stage("api").outcome == "pass"


def test_report_markdown_lists_labels_and_mismatches(fixture_report: pipeline.E2EReport) -> None:
    md = render_markdown(fixture_report)
    assert "E2E verdict: **PASS**" in md
    assert "## Interface mismatches for window 00" in md
    assert "conference id mismatch" in md
    assert "| official | w03 | fixture | fixture |" in md
    assert "luma:host:" not in md  # organizer ids are aggregated, not dumped


def test_probe_offline_writes_report(tmp_path: Path, no_network: None) -> None:
    import runpy

    probe = Path(__file__).resolve().parents[2] / "scripts" / "probes" / "integration.py"
    module = runpy.run_path(str(probe))
    out = tmp_path / "integration.md"
    assert module["main"](["--offline", "--out", str(out)]) == 0
    text = out.read_text(encoding="utf-8")
    assert "fixture E2E" in text and "Skipped (--offline)" in text


def test_fixture_slices_are_deterministic() -> None:
    first = [(s.name, s.count) for s in fixture_slices()]
    second = [(s.name, s.count) for s in fixture_slices()]
    assert first == second


@pytest.mark.skipif(os.getenv("CONFERGE_LIVE") != "1", reason="set CONFERGE_LIVE=1 for live E2E")
def test_live_e2e_public_endpoints() -> None:
    report = asyncio.run(run_e2e("live", include_backup=False, timeout=120))
    for s in report.slices:
        assert s.source_mode == "live"
        assert s.status in {"ok", "degraded", "failed"}
    assert report.stage("api").outcome == "pass"


def test_merged_agents_run_in_planning(fixture_report: pipeline.E2EReport) -> None:
    detail = fixture_report.stage("planning").detail
    merged = {c.component.slug for c in fixture_report.components if c.present}
    if "antifomo" in merged:
        assert "antifomo (merged): ok" in detail
    if "replanner" in merged:
        assert "replanner (merged): ok" in detail
