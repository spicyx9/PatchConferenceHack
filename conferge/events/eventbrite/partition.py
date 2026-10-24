"""Date-range partitioning for Eventbrite's result ceiling (independent implementation).

Eventbrite search stops paginating after about 19 pages of 50 (~950 results)
even when object_count is larger. A range whose declared total exceeds the cap
is split in half recursively; a single day still above the cap cannot be split
further and is drained up to the ceiling with an explicit page_cap warning.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import date, timedelta

DEFAULT_CAP = 900


@dataclass(frozen=True)
class Window:
    start: date
    end: date  # inclusive
    declared_total: int | None = None
    capped: bool = False

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1


@dataclass
class PartitionPlan:
    windows: list[Window] = field(default_factory=list)
    probes: int = 0
    warnings: list[str] = field(default_factory=list)


def split(start: date, end: date) -> tuple[tuple[date, date], tuple[date, date]]:
    """Split an inclusive range into two non-overlapping inclusive halves."""
    if end <= start:
        raise ValueError("cannot split a single-day range")
    middle = start + timedelta(days=((end - start).days) // 2)
    return (start, middle), (middle + timedelta(days=1), end)


async def plan_windows(
    count: Callable[[date, date], Awaitable[int]], start: date, end: date, *,
    cap: int = DEFAULT_CAP, max_probes: int = 64,
) -> PartitionPlan:
    """Find windows whose declared totals fit under `cap`.

    `count(start, end)` returns the declared object_count for that range.
    Windows are returned in chronological order.
    """
    if start > end:
        raise ValueError("start must be <= end")
    plan = PartitionPlan()
    stack: list[tuple[date, date]] = [(start, end)]
    found: list[Window] = []
    while stack:
        lo, hi = stack.pop()
        if plan.probes >= max_probes:
            plan.warnings.append(f"partition_probe_budget_exhausted:{lo}..{hi}")
            found.append(Window(lo, hi, None, capped=True))
            continue
        total = await count(lo, hi)
        plan.probes += 1
        if total <= cap:
            found.append(Window(lo, hi, total))
        elif lo == hi:
            plan.warnings.append(f"page_cap:{lo} declares {total} > cap {cap}")
            found.append(Window(lo, hi, total, capped=True))
        else:
            first, second = split(lo, hi)
            stack.extend([second, first])
    plan.windows = sorted(found, key=lambda window: window.start)
    return plan
