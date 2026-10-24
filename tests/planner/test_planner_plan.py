"""Per-day reverse plan: overlaps with travel, rejections, constraints, budget."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

import pytest
from planner_helpers import make_ctx, plan_of, planned_ids, raw_context, rejected_map, run_planner

from conferge.agents.planner.plan import PlanCandidate, PlanConstraints, optimize
from conferge.core.schemas import Event, Venue

FORT_MASON = {"name": "FM", "latitude": 37.806, "longitude": -122.432,
              "coordinate_precision": "exact"}
MISSION = {"name": "Mission", "latitude": 37.7599, "longitude": -122.4148,
           "coordinate_precision": "approximate"}


def _event(event_id: str, start: str | None, end: str | None, **extra: Any) -> Event:
    return Event.model_validate({
        "id": event_id, "title": event_id, "event_type": "meetup",
        "start_at": start, "end_at": end, "conference_relation": "official",
        "relation_evidence": ["test"], **extra,
    })


def _without(raw: dict[str, Any], event_id: str) -> dict[str, Any]:
    raw["events"] = [e for e in raw["events"] if e["id"] != event_id]
    return raw


async def test_no_overlap_including_travel() -> None:
    res = await run_planner(make_ctx())
    for day in plan_of(res)["days"]:
        items = day["items"]
        assert items[0]["travel_from_previous"] is None
        for prev, nxt in zip(items, items[1:], strict=False):
            gap = (datetime.fromisoformat(nxt["start"])
                   - datetime.fromisoformat(prev["end"])).total_seconds() / 60
            travel = nxt["travel_from_previous"]
            assert travel is not None and "minutes" in travel and travel["method"]
            assert gap >= travel["minutes"], (prev["id"], nxt["id"], gap, travel)
        for item in items:
            assert item["start"] and item["end"] and item["start"] < item["end"]
            assert datetime.fromisoformat(item["start"]).date().isoformat() == day["date"]


async def test_items_carry_reason_path_and_source() -> None:
    res = await run_planner(make_ctx())
    for day in plan_of(res)["days"]:
        for item in day["items"]:
            assert item["reason"].startswith("score ")
            assert item["source_url"] or item["path"]
            assert item["fixed"] is False


async def test_untimed_cancelled_and_weak_events_rejected_with_reasons() -> None:
    rejected = rejected_map(await run_planner(make_ctx()))
    assert rejected["fx-side-untimed"] == "start or end time unknown; not scheduled"
    assert rejected["fx-side-cancelled"] == "status cancelled"
    assert "relation_score 0.2" in rejected["fx-side-weak"]
    assert "overlaps" in rejected["fx-side-vc-dinner"]


async def test_every_event_is_planned_or_rejected() -> None:
    res = await run_planner(make_ctx())
    planned, rejected = set(planned_ids(res)), set(rejected_map(res))
    assert not planned & rejected
    assert planned | rejected == {e.id for e in make_ctx().events}


async def test_blocked_slot_removes_overlapping_event() -> None:
    blocked = [{"start": "2026-10-28T10:00:00-07:00", "end": "2026-10-28T10:30:00-07:00",
                "reason": "investor call"}]
    res = await run_planner(make_ctx(blocked=blocked))
    assert "fx-s-agent-infra" not in planned_ids(res)
    assert rejected_map(res)["fx-s-agent-infra"] == "overlaps blocked slot (investor call)"
    assert "fx-s-seed-panel" in planned_ids(res)
    assert not any("ignored blocked slot" in e for e in res.errors)


async def test_blocked_slot_in_utc_is_compared_as_instant() -> None:
    # 17:00Z == 10:00 PDT
    blocked = [{"start": "2026-10-28T17:00:00+00:00", "end": "2026-10-28T17:30:00+00:00"}]
    res = await run_planner(make_ctx(blocked=blocked))
    assert "fx-s-agent-infra" not in planned_ids(res)


async def test_naive_blocked_datetimes_ignored_with_warning() -> None:
    blocked = [{"start": "2026-10-28T10:00:00", "end": "2026-10-28T10:30:00"}]
    res = await run_planner(make_ctx(blocked=blocked))
    assert any("ignored blocked slot" in e and "naive" in e for e in res.errors)
    assert "fx-s-agent-infra" in planned_ids(res)


async def test_malformed_blocked_slot_ignored_with_warning() -> None:
    res = await run_planner(make_ctx(blocked=[{"start": "not a date"}, {"end": "x"}]))
    assert sum("ignored blocked slot" in e for e in res.errors) == 2
    assert plan_of(res)["days"]


async def test_max_items_per_day_one() -> None:
    res = await run_planner(make_ctx(max_items_per_day=1))
    days = plan_of(res)["days"]
    assert all(len(d["items"]) == 1 for d in days)
    by_date = {d["date"]: d["items"][0]["id"] for d in days}
    # highest-scored event of each day wins
    assert by_date == {"2026-10-28": "fx-side-agents-night", "2026-10-29": "fx-s-copilot"}
    rejected = rejected_map(res)
    assert "already has 1 items" in rejected["fx-s-seed-panel"]
    assert "already has 1 items" in rejected["fx-s-agent-infra"]


@pytest.mark.parametrize("bad", [0, -1, "3"])
async def test_invalid_max_items_reported(bad: object) -> None:
    res = await run_planner(make_ctx(max_items_per_day=bad))
    assert any("invalid max_items_per_day" in e for e in res.errors)
    assert len(planned_ids(res)) == 4


async def test_paid_event_over_budget_is_dropped() -> None:
    raw = _without(raw_context(), "fx-side-agents-night")
    raw["budget_usd"] = "10"
    res = await run_planner(make_ctx(raw))
    assert "fx-side-vc-dinner" not in planned_ids(res)
    reason = rejected_map(res)["fx-side-vc-dinner"]
    assert reason.startswith("over budget")
    assert "40" in reason and "10" in reason


async def test_paid_event_within_budget_is_kept() -> None:
    raw = _without(raw_context(), "fx-side-agents-night")
    raw["budget_usd"] = "40"
    res = await run_planner(make_ctx(raw))
    assert "fx-side-vc-dinner" in planned_ids(res)
    assert "fx-side-vc-dinner" not in rejected_map(res)


async def test_fixed_event_placed_first_and_not_dropped_by_budget() -> None:
    raw = raw_context(fixed_event_ids=["fx-side-vc-dinner"])
    raw["budget_usd"] = "0"
    res = await run_planner(make_ctx(raw))
    assert "fx-side-vc-dinner" in planned_ids(res)
    assert "fx-side-agents-night" not in planned_ids(res)
    assert "overlaps" in rejected_map(res)["fx-side-agents-night"]
    item = next(i for d in plan_of(res)["days"] for i in d["items"]
                if i["id"] == "fx-side-vc-dinner")
    assert item["fixed"] is True


async def test_unknown_prices_flagged_in_warnings() -> None:
    res = await run_planner(make_ctx())
    assert any("unknown price" in w for w in plan_of(res)["warnings"])


async def test_optimize_travel_gap_rejects_tight_hop() -> None:
    a = _event("a", "2026-10-28T10:00:00-07:00", "2026-10-28T11:00:00-07:00", venue=FORT_MASON)
    b = _event("b", "2026-10-28T11:05:00-07:00", "2026-10-28T12:00:00-07:00", venue=MISSION)
    out = await optimize([PlanCandidate(a, 50, "r"), PlanCandidate(b, 40, "r")], PlanConstraints())
    assert [i["id"] for d in out["days"] for i in d["items"]] == ["a"]
    assert "estimated travel needs" in out["rejected"][0]["reason"]


async def test_optimize_unknown_venues_use_buffer() -> None:
    a = _event("a", "2026-10-28T10:00:00-07:00", "2026-10-28T11:00:00-07:00")
    b = _event("b", "2026-10-28T11:10:00-07:00", "2026-10-28T12:00:00-07:00")
    c = _event("c", "2026-10-28T11:30:00-07:00", "2026-10-28T12:30:00-07:00",
               venue=Venue(name="Elsewhere").model_dump())
    out = await optimize([PlanCandidate(a, 60, "r"), PlanCandidate(b, 50, "r"),
                          PlanCandidate(c, 10, "r")], PlanConstraints())
    rejected = {r["id"]: r["reason"] for r in out["rejected"]}
    assert "30 min" in rejected["b"]
    assert [i["id"] for d in out["days"] for i in d["items"]] == ["a", "c"]


async def test_optimize_groups_by_conference_timezone() -> None:
    # 23:30 PDT on the 28th is the 29th in UTC; it must stay on the 28th.
    late = _event("late", "2026-10-28T23:30:00-07:00", "2026-10-28T23:59:00-07:00")
    out = await optimize([PlanCandidate(late, 50, "r")], PlanConstraints())
    assert out["days"][0]["date"] == "2026-10-28"


async def test_optimize_original_breaks_ties() -> None:
    a = _event("a", "2026-10-28T10:00:00-07:00", "2026-10-28T11:00:00-07:00")
    b = _event("b", "2026-10-28T10:00:00-07:00", "2026-10-28T11:00:00-07:00")
    cands = [PlanCandidate(a, 50, "r"), PlanCandidate(b, 50, "r")]
    first = await optimize(cands, PlanConstraints())
    kept = await optimize(cands, PlanConstraints(), original=["b"])
    assert [i["id"] for i in first["days"][0]["items"]] == ["a"]
    assert [i["id"] for i in kept["days"][0]["items"]] == ["b"]


async def test_optimize_low_score_rejected_unless_fixed() -> None:
    a = _event("a", "2026-10-28T10:00:00-07:00", "2026-10-28T11:00:00-07:00")
    out = await optimize([PlanCandidate(a, 0.0, "r")], PlanConstraints())
    assert out["rejected"][0]["reason"].startswith("score 0.0 below")
    fixed = await optimize([PlanCandidate(a, 0.0, "r")], PlanConstraints(fixed_ids={"a"}))
    assert [i["id"] for i in fixed["days"][0]["items"]] == ["a"]


async def test_budget_drop_frees_slot_for_overlapping_free_event() -> None:
    paid = _event("paid", "2026-10-28T19:00:00-07:00", "2026-10-28T21:00:00-07:00",
                  price_min="40", currency="USD", is_free=False)
    free = _event("free", "2026-10-28T19:30:00-07:00", "2026-10-28T21:00:00-07:00", is_free=True)
    out = await optimize([PlanCandidate(paid, 80, "r"), PlanCandidate(free, 50, "r")],
                         PlanConstraints(budget_usd=Decimal("10")))
    assert [i["id"] for d in out["days"] for i in d["items"]] == ["free"]
    assert any(r["id"] == "paid" and "over budget" in r["reason"] for r in out["rejected"])
