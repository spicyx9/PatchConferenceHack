"""Reverse plan: greedy per-day optimizer over scored events.

Interface ``optimize(candidates, constraints, original=None)`` is the seam
window 10 replaces with a Pathfinder/PuLP optimizer. Rules:

* only events with both start and end times are schedulable (no invented times);
* no overlap, counting the estimated travel between consecutive venues;
* at most ``max_items_per_day`` items per day, blocked slots respected;
* user-fixed events are placed first; ``original`` keeps prior picks on ties;
* known prices count against the budget, unknown prices are flagged.

Days are optimized concurrently (one coroutine per day, Devoxx pattern).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from conferge.agents.planner.candidates import known_cost
from conferge.agents.planner.geo import estimate
from conferge.core.schemas import Event


@dataclass
class PlanCandidate:
    event: Event
    score: float
    reason: str
    path: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class BlockedSlot:
    start: datetime
    end: datetime
    reason: str


@dataclass
class PlanConstraints:
    timezone: str = "America/Los_Angeles"
    max_items_per_day: int = 6
    min_score: float = 1.0
    blocked: list[BlockedSlot] = field(default_factory=list)
    fixed_ids: set[str] = field(default_factory=set)
    budget_usd: Decimal | None = None

    @classmethod
    def from_mapping(cls, raw: dict[str, Any], timezone: str,
                     budget_usd: Decimal | None) -> tuple[PlanConstraints, list[str]]:
        """Parse ``AgentContext.constraints``; bad entries are reported, not guessed."""
        warnings: list[str] = []
        blocked: list[BlockedSlot] = []
        for item in raw.get("blocked", []) or []:
            try:
                start = datetime.fromisoformat(str(item["start"]))
                end = datetime.fromisoformat(str(item["end"]))
                if start.tzinfo is None or end.tzinfo is None:
                    raise ValueError("naive datetime")
                blocked.append(BlockedSlot(start, end, str(item.get("reason", "blocked"))))
            except (KeyError, TypeError, ValueError) as exc:
                warnings.append(f"ignored blocked slot {item!r}: {exc}")
        max_items = raw.get("max_items_per_day", 6)
        if not isinstance(max_items, int) or max_items < 1:
            warnings.append(f"invalid max_items_per_day {max_items!r}; using 6")
            max_items = 6
        return cls(
            timezone=timezone, max_items_per_day=max_items, blocked=blocked,
            fixed_ids={str(i) for i in raw.get("fixed_event_ids", []) or []},
            budget_usd=budget_usd,
        ), warnings


def _travel(a: Event, b: Event) -> dict[str, object]:
    return estimate(a.venue, b.venue).as_dict()


def _fits(cand: PlanCandidate, chosen: list[PlanCandidate],
          blocked: list[BlockedSlot]) -> str | None:
    ev = cand.event
    assert ev.start_at and ev.end_at
    for slot in blocked:
        if ev.start_at < slot.end and slot.start < ev.end_at:
            return f"overlaps blocked slot ({slot.reason})"
    for other in chosen:
        ot = other.event
        assert ot.start_at and ot.end_at
        if ev.start_at < ot.end_at and ot.start_at < ev.end_at:
            return f"overlaps '{ot.title}' (score {other.score})"
        if ev.end_at <= ot.start_at:
            gap = (ot.start_at - ev.end_at).total_seconds() / 60
            need = estimate(ev.venue, ot.venue).minutes
        else:
            gap = (ev.start_at - ot.end_at).total_seconds() / 60
            need = estimate(ot.venue, ev.venue).minutes
        if gap < need:
            return f"only {int(gap)} min from '{ot.title}', estimated travel needs {need} min"
    return None


async def _plan_day(day: date, cands: list[PlanCandidate], constraints: PlanConstraints,
                    original: set[str]) -> tuple[dict[str, Any], list[dict[str, str]]]:
    order = sorted(cands, key=lambda c: (
        c.event.id not in constraints.fixed_ids, -c.score, c.event.id not in original,
        c.event.start_at, c.event.id))
    chosen: list[PlanCandidate] = []
    rejected: list[dict[str, str]] = []
    for cand in order:
        if len(chosen) >= constraints.max_items_per_day:
            rejected.append({"id": cand.event.id, "reason":
                             f"day {day.isoformat()} already has {constraints.max_items_per_day} items"})
            continue
        clash = _fits(cand, chosen, constraints.blocked)
        if clash:
            rejected.append({"id": cand.event.id, "reason": clash})
            continue
        chosen.append(cand)
    chosen.sort(key=lambda c: (c.event.start_at, c.event.id))
    items = []
    previous: Event | None = None
    for cand in chosen:
        ev = cand.event
        items.append({
            "kind": ev.event_type, "id": ev.id, "title": ev.title,
            "start": ev.start_at.isoformat() if ev.start_at else None,
            "end": ev.end_at.isoformat() if ev.end_at else None,
            "venue": ev.venue.name if ev.venue else None, "room": ev.room,
            "score": cand.score, "reason": cand.reason, "path": cand.path,
            "fixed": ev.id in constraints.fixed_ids,
            "travel_from_previous": _travel(previous, ev) if previous else None,
            "source_url": str(ev.source_url) if ev.source_url else None,
        })
        previous = ev
    return {"date": day.isoformat(), "items": items}, rejected


def _apply_budget(days: list[dict[str, Any]], by_id: dict[str, PlanCandidate],
                  budget: Decimal | None) -> tuple[list[dict[str, str]], list[str]]:
    rejected: list[dict[str, str]] = []
    warnings: list[str] = []
    planned = [item for d in days for item in d["items"]]
    unknown = [i["id"] for i in planned if known_cost(by_id[i["id"]].event) is None]
    if unknown:
        warnings.append(f"{len(unknown)} planned item(s) have unknown price; not counted in budget")
    if budget is None:
        return rejected, warnings
    spent = sum((known_cost(by_id[i["id"]].event) or Decimal(0) for i in planned), Decimal(0))
    # Drop the lowest-scored paid, non-fixed items until the known spend fits.
    for item in sorted(planned, key=lambda i: (i["score"], i["id"])):
        if spent <= budget:
            break
        cost = known_cost(by_id[item["id"]].event) or Decimal(0)
        if cost <= 0 or item["fixed"]:
            continue
        for day in days:
            if item in day["items"]:
                day["items"].remove(item)
        spent -= cost
        rejected.append({"id": item["id"], "reason": f"over budget (known spend {spent + cost} > {budget})"})
    return rejected, warnings


async def optimize(candidates: list[PlanCandidate], constraints: PlanConstraints,
                   original: list[str] | None = None) -> dict[str, Any]:
    """Return ``{"days": [...], "rejected": [...], "warnings": [...]}``."""
    tz = ZoneInfo(constraints.timezone)
    rejected: list[dict[str, str]] = []
    by_day: dict[date, list[PlanCandidate]] = {}
    for cand in candidates:
        ev = cand.event
        if ev.status in {"cancelled", "sold_out"}:
            rejected.append({"id": ev.id, "reason": f"status {ev.status}"})
        elif not (ev.start_at and ev.end_at):
            rejected.append({"id": ev.id, "reason": "start or end time unknown; not scheduled"})
        elif cand.score < constraints.min_score and ev.id not in constraints.fixed_ids:
            rejected.append({"id": ev.id, "reason": f"score {cand.score} below {constraints.min_score}"})
        else:
            by_day.setdefault(ev.start_at.astimezone(tz).date(), []).append(cand)
    keep = set(original or [])
    by_id = {c.event.id: c for c in candidates}
    budget_rejected: list[dict[str, str]] = []
    # Re-plan after each budget drop so a freed slot can go to the next best event.
    for _ in range(len(candidates) + 1):
        results = await asyncio.gather(*(
            _plan_day(day, cands, constraints, keep) for day, cands in sorted(by_day.items())
        ))
        days = [day for day, _ in results]
        dropped, warnings = _apply_budget(days, by_id, constraints.budget_usd)
        if not dropped:
            break
        budget_rejected.extend(dropped)
        gone = {r["id"] for r in dropped}
        by_day = {d: [c for c in cs if c.event.id not in gone] for d, cs in by_day.items()}
    for _, day_rejected in results:
        rejected.extend(day_rejected)
    rejected.extend(budget_rejected)
    rejected.sort(key=lambda r: r["id"])
    return {"days": days, "rejected": rejected, "warnings": warnings}
