"""Per-source isolation: one adapter raising does not stop the others (integration/sources.py)."""

from __future__ import annotations

import asyncio

from conferge.integration.pipeline_view import build_rows
from conferge.integration.sources import (
    SourceSlice,
    live_slices,
    overall_report,
    sanitize,
)


async def _ok_luma() -> SourceSlice:
    await asyncio.sleep(0.01)
    return SourceSlice("luma", "01", "live", "live", "ok")


async def _boom() -> SourceSlice:
    raise RuntimeError("upstream 500 at https://api.example.com/v1?token=abc123 api_key=SECRET42")


async def _slow() -> SourceSlice:
    await asyncio.sleep(5)
    return SourceSlice("slow", "02", "live", "live", "ok")


def _with_event(s: SourceSlice) -> SourceSlice:
    from conferge.api.data import load_fixture

    s.events = load_fixture().events[:2]
    return s


async def _ok_with_events() -> SourceSlice:
    return _with_event(SourceSlice("partiful", "01", "live", "live", "ok"))


RUNNERS = {"luma": ("01", _ok_luma), "eventbrite": ("02", _boom),
           "partiful": ("01", _ok_with_events), "slow": ("02", _slow)}


def test_one_source_raising_keeps_the_others() -> None:
    slices = asyncio.run(live_slices(timeout=0.5, runners=RUNNERS))
    by = {s.name: s for s in slices}
    assert set(by) == {"luma", "eventbrite", "partiful", "slow"}
    assert by["luma"].status == "ok" and by["partiful"].count == 2
    failed = by["eventbrite"]
    assert failed.status == "failed" and failed.count == 0
    msg = failed.errors[0]
    assert msg.startswith("RuntimeError: upstream 500")
    assert "abc123" not in msg and "SECRET42" not in msg
    assert by["slow"].status == "failed" and by["slow"].errors == ["timeout after 0s"]
    assert all(s.duration_s is not None for s in slices)
    assert by["slow"].duration_s >= 0.4


def test_failed_source_has_a_pipeline_row_and_overall_is_degraded() -> None:
    slices = asyncio.run(live_slices(timeout=0.5, runners=RUNNERS))
    rows = [r for r in build_rows(slices, {}, {}) if r["source"] == "eventbrite"]
    assert len(rows) == 1 and rows[0]["status"] == "failed"
    assert "SECRET42" not in rows[0]["reason"]
    report = overall_report(slices)
    assert report.status == "degraded"
    assert report.fetched_count == 4 and report.unique_count == 1
    assert any(e.startswith("eventbrite: RuntimeError") for e in report.errors)


def test_overall_report_ok_and_failed() -> None:
    good = [_with_event(SourceSlice("a", "01", "live", "live", "ok"))]
    assert overall_report(good).status == "ok"
    assert overall_report([SourceSlice("b", "01", "live", "live", "failed")]).status == "failed"


def test_sanitize_redacts_and_caps() -> None:
    out = sanitize("Bearer abc.def https://x.io/p?key=1&sig=2 password: hunter2 " + "z" * 500)
    assert "abc.def" not in out and "sig=2" not in out and "hunter2" not in out
    assert out.startswith("Bearer=<redacted> https://x.io/p?…") and len(out) <= 200


def test_status_display_failed_partial_ok() -> None:
    from conferge.integration.sources import status_display

    partial = _with_event(SourceSlice("partiful", "01", "live", "live", "degraded"))
    shown = status_display([partial, SourceSlice("luma", "01", "live", "live", "ok")])
    assert shown == {"label": "partial", "reason": "Partiful not exhausted, 2 events kept"}
    slices = asyncio.run(live_slices(timeout=0.5, runners=RUNNERS))
    shown = status_display([*slices, partial])
    assert shown["label"] == "failed"  # a source that raised outranks a partial one
    assert shown["reason"].startswith("Eventbrite failed (RuntimeError: upstream 500")
    assert "SECRET42" not in shown["reason"] and "degraded" not in shown["reason"]
    assert status_display([_with_event(SourceSlice("a", "01", "live", "live", "ok"))])["label"] == "ok"


def test_aggregator_fixture_keeps_only_the_anchor_page() -> None:
    from conferge.integration.sources import fixture_slices

    s = fixture_slices(["aggregators"])[0]
    assert len(s.events) == 7  # conferenceparties/github26, same page as the live run
    assert all(e.start_at is None or e.start_at.month == 10 for e in s.events)
    report = s.reports[0]
    assert report.fetched_count == 20 and report.unique_count == 7
    assert any("reinvent2026" in w for w in report.warnings)
