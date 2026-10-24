"""Date-range splitting for the Eventbrite result ceiling."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from conferge.events.eventbrite.partition import plan_windows, split


def _days(lo: date, hi: date) -> set[date]:
    return {lo + timedelta(days=i) for i in range((hi - lo).days + 1)}


@pytest.mark.parametrize(
    ("start", "end"),
    [
        (date(2026, 10, 1), date(2026, 10, 2)),
        (date(2026, 10, 1), date(2026, 10, 3)),
        (date(2026, 10, 1), date(2026, 10, 10)),
        (date(2026, 10, 27), date(2026, 11, 3)),
        (date(2026, 12, 30), date(2027, 1, 2)),
    ],
)
def test_split_halves_inclusive_without_overlap(start: date, end: date) -> None:
    (a_lo, a_hi), (b_lo, b_hi) = split(start, end)
    assert a_lo == start and b_hi == end
    assert b_lo == a_hi + timedelta(days=1)
    assert a_lo <= a_hi and b_lo <= b_hi
    first, second = _days(a_lo, a_hi), _days(b_lo, b_hi)
    assert not first & second
    assert first | second == _days(start, end)
    assert abs(len(first) - len(second)) <= 1


def test_split_known_values() -> None:
    assert split(date(2026, 10, 1), date(2026, 10, 10)) == (
        (date(2026, 10, 1), date(2026, 10, 5)),
        (date(2026, 10, 6), date(2026, 10, 10)),
    )
    assert split(date(2026, 10, 1), date(2026, 10, 2)) == (
        (date(2026, 10, 1), date(2026, 10, 1)),
        (date(2026, 10, 2), date(2026, 10, 2)),
    )


def test_split_single_day_raises() -> None:
    with pytest.raises(ValueError):
        split(date(2026, 10, 1), date(2026, 10, 1))


def _fake_count(per_day: dict[date, int], calls: list[tuple[date, date]]):
    async def count(lo: date, hi: date) -> int:
        calls.append((lo, hi))
        return sum(n for day, n in per_day.items() if lo <= day <= hi)

    return count


async def test_plan_windows_fits_without_split() -> None:
    calls: list[tuple[date, date]] = []
    per_day = {date(2026, 10, 27): 10, date(2026, 10, 28): 20}
    plan = await plan_windows(
        _fake_count(per_day, calls), date(2026, 10, 27), date(2026, 10, 30), cap=100
    )
    assert len(plan.windows) == 1
    window = plan.windows[0]
    assert (window.start, window.end, window.declared_total, window.capped) == (
        date(2026, 10, 27), date(2026, 10, 30), 30, False,
    )
    assert plan.probes == 1 and plan.warnings == []


async def test_plan_windows_recurses_until_under_cap_in_order() -> None:
    calls: list[tuple[date, date]] = []
    start, end = date(2026, 10, 1), date(2026, 10, 16)
    per_day = {start + timedelta(days=i): 30 for i in range(16)}  # 480 total
    plan = await plan_windows(_fake_count(per_day, calls), start, end, cap=100)
    assert plan.warnings == []
    assert all(w.declared_total is not None and w.declared_total <= 100 for w in plan.windows)
    assert not any(w.capped for w in plan.windows)
    # chronological, contiguous, non-overlapping, covering the whole range
    assert plan.windows[0].start == start and plan.windows[-1].end == end
    for prev, nxt in zip(plan.windows, plan.windows[1:], strict=False):
        assert nxt.start == prev.end + timedelta(days=1)
    assert sum(w.declared_total or 0 for w in plan.windows) == 480
    assert plan.probes == len(calls)
    assert len(plan.windows) > 1


async def test_plan_windows_single_day_above_cap_is_capped_with_warning() -> None:
    calls: list[tuple[date, date]] = []
    busy = date(2026, 10, 28)
    per_day = {date(2026, 10, 27): 10, busy: 5000, date(2026, 10, 29): 10}
    plan = await plan_windows(
        _fake_count(per_day, calls), date(2026, 10, 27), date(2026, 10, 29), cap=900
    )
    capped = [w for w in plan.windows if w.capped]
    assert len(capped) == 1
    assert (capped[0].start, capped[0].end, capped[0].declared_total) == (busy, busy, 5000)
    assert any(warning.startswith("page_cap:") for warning in plan.warnings)
    assert [w.start for w in plan.windows] == sorted(w.start for w in plan.windows)
    covered = set().union(*(_days(w.start, w.end) for w in plan.windows))
    assert covered == _days(date(2026, 10, 27), date(2026, 10, 29))


async def test_plan_windows_start_after_end_raises() -> None:
    calls: list[tuple[date, date]] = []
    with pytest.raises(ValueError):
        await plan_windows(_fake_count({}, calls), date(2026, 10, 2), date(2026, 10, 1))
    assert calls == []


async def test_plan_windows_probe_budget_marks_remaining_capped() -> None:
    calls: list[tuple[date, date]] = []
    start = date(2026, 10, 1)
    per_day = {start + timedelta(days=i): 1000 for i in range(8)}
    plan = await plan_windows(
        _fake_count(per_day, calls), start, start + timedelta(days=7), cap=900, max_probes=3
    )
    assert plan.probes == 3
    assert any("partition_probe_budget_exhausted" in w for w in plan.warnings)
    assert any(w.capped and w.declared_total is None for w in plan.windows)
