from __future__ import annotations

from datetime import time
from decimal import Decimal

from w10_helpers import FAR, FORT_MASON, assert_no_overlap, at, ev

from conferge.agents.antifomo import (
    Candidate, Constraints, TimeSlot, build_candidates, explain, optimize,
)
from conferge.agents.antifomo.fixture import load_fixture


def cand(e, u, cost=None):
    return Candidate(event=e, utility=u, cost_usd=cost)


def codes(plan):
    return {r.event_id: r.code for r in plan.rejected}


def test_fixture_plan_has_no_overlap_including_travel():
    fx = load_fixture()
    c = Constraints(timezone=fx.conference.timezone)
    plan = optimize(build_candidates(fx.events, fx.goals, fx.people), c)
    assert plan.items
    assert_no_overlap(plan, {e.id: e for e in fx.events}, c)
    assert codes(plan)["ev-29-hack-night"] == "unavailable"
    assert codes(plan)["ev-29-rooftop-tba"] == "time_unknown"


def test_dense_synthetic_day_no_overlap_and_max_per_day():
    events = [ev(f"e{i:02d}", at(28, 8 + i // 2, 30 * (i % 2)), at(28, 9 + i // 2, 30 * (i % 2)),
                 FAR if i % 3 == 0 else FORT_MASON) for i in range(16)]
    cands = [cand(e, 10 + (i * 7) % 23) for i, e in enumerate(events)]
    c = Constraints(max_per_day=4)
    plan = optimize(cands, c)
    assert 0 < len(plan.items) <= 4
    assert_no_overlap(plan, {e.id: e for e in events}, c)
    assert all(r.code in {"conflict", "day_full", "low_utility"} for r in plan.rejected)


def test_blocked_slot_excludes_overlapping_event():
    a, b = ev("a", at(28, 9), at(28, 10)), ev("b", at(28, 13), at(28, 14))
    slot = TimeSlot(id="m1", label="Investor meeting", start=at(28, 9, 30), end=at(28, 11))
    plan = optimize([cand(a, 50), cand(b, 40)], Constraints(blocked=[slot]))
    assert plan.event_ids == ["b"]
    assert codes(plan)["a"] == "blocked_slot"


def test_fixed_kept_and_clashing_rejected():
    a, b = ev("a", at(28, 9), at(28, 10)), ev("b", at(28, 9, 30), at(28, 10, 30))
    plan = optimize([cand(a, 10), cand(b, 90)], Constraints(fixed_event_ids=["a"]))
    assert plan.event_ids == ["a"]
    assert plan.items[0].fixed
    assert codes(plan)["b"] == "conflicts_with_fixed"


def test_excluded_sold_out_cancelled_and_unknown_time():
    events = [
        ev("x", at(28, 9), at(28, 10)),
        ev("s", at(28, 11), at(28, 12), status="sold_out"),
        ev("c", at(28, 13), at(28, 14), status="cancelled"),
        ev("t", None, None),
        ev("ok", at(28, 15), at(28, 16)),
    ]
    plan = optimize([cand(e, 50) for e in events], Constraints(excluded_event_ids=["x"]))
    assert plan.event_ids == ["ok"]
    assert codes(plan) == {"x": "excluded_by_user", "s": "unavailable", "c": "unavailable",
                           "t": "time_unknown"}


def test_daily_window():
    early, mid, late = (ev("early", at(28, 7), at(28, 8)), ev("mid", at(28, 10), at(28, 11)),
                        ev("late", at(28, 22), at(28, 23, 30)))
    c = Constraints(day_start=time(8, 0), day_end=time(22, 0))
    plan = optimize([cand(early, 50), cand(mid, 50), cand(late, 50)], c)
    assert plan.event_ids == ["mid"]
    assert codes(plan) == {"early": "outside_daily_window", "late": "outside_daily_window"}


def test_budget_drops_lowest_utility_per_dollar_and_unknown_not_zero():
    a = ev("a", at(28, 9), at(28, 10))
    b = ev("b", at(28, 11), at(28, 12))
    u = ev("u", at(28, 13), at(28, 14))
    cands = [cand(a, 60, Decimal("30")), cand(b, 50, Decimal("50")), cand(u, 40, None)]
    plan = optimize(cands, Constraints(budget_usd=Decimal("40")))
    assert plan.event_ids == ["a", "u"]
    assert codes(plan)["b"] == "over_budget"
    assert plan.known_cost_usd == Decimal("30")
    assert plan.unknown_cost_event_ids == ["u"]


def test_require_registration_evidence():
    a = ev("a", at(28, 9), at(28, 10), registration_url=None)
    plan = optimize([cand(a, 50)], Constraints(require_registration_evidence=True))
    assert plan.items == []
    assert codes(plan)["a"] == "missing_registration_evidence"


def test_travel_buffer_far_conflicts_same_venue_fits():
    a = ev("a", at(28, 9), at(28, 10))
    far = ev("far", at(28, 10, 5), at(28, 11), FAR)
    same = ev("same", at(28, 10, 5), at(28, 11), FORT_MASON)
    plan = optimize([cand(a, 50), cand(far, 40)])
    assert plan.event_ids == ["a"]
    assert codes(plan)["far"] == "conflict"
    plan2 = optimize([cand(a, 50), cand(same, 40)])
    assert plan2.event_ids == ["a", "same"]
    assert plan2.items[1].travel_basis == "same_venue"


def test_unknown_venue_uses_default_travel_with_warning():
    a = ev("a", at(28, 9), at(28, 10))
    hidden = ev("h", at(28, 10, 30), at(28, 11), {"name": "Secret", "coordinate_precision": "unknown"})
    plan = optimize([cand(a, 50), cand(hidden, 40)], Constraints(default_travel_minutes=20))
    item = plan.item("h")
    assert item and item.travel_basis == "unknown_default"
    assert item.travel_minutes_from_previous == 20
    assert any("travel time assumed" in w for w in item.warnings)
    plan2 = optimize([cand(a, 50), cand(hidden, 40)], Constraints(default_travel_minutes=45))
    assert plan2.event_ids == ["a"]


def test_availability_label_never_claims_available():
    a = ev("a", at(28, 9), at(28, 10), registration_url=None)
    b = ev("b", at(28, 11), at(28, 12))
    plan = optimize([cand(a, 50), cand(b, 50)])
    labels = {i.event_id: i.availability for i in plan.items}
    assert labels == {"a": "no_registration_evidence", "b": "registration_link_found"}
    assert any("registration" in w for w in plan.item("a").warnings)
    assert "available" not in {i.availability for i in plan.items}


def test_minimal_change_identity_and_penalty():
    a, b = ev("a", at(28, 9), at(28, 10)), ev("b", at(28, 11), at(28, 12))
    base = optimize([cand(a, 50), cand(b, 40)])
    again = optimize([cand(a, 50), cand(b, 40)], original=base)
    assert again.event_ids == base.event_ids and again.changes_vs_original == 0
    rival_small = ev("r", at(28, 11, 15), at(28, 12, 15))
    small = optimize([cand(a, 50), cand(b, 40), cand(rival_small, 45)],
                     Constraints(change_penalty=8), original=base)
    assert small.event_ids == ["a", "b"]
    big = optimize([cand(a, 50), cand(b, 40), cand(rival_small, 70)],
                   Constraints(change_penalty=8), original=base)
    assert big.event_ids == ["a", "r"]
    assert big.changes_vs_original == 2


def test_determinism_and_explain():
    fx = load_fixture()
    c1 = build_candidates(fx.events, fx.goals, fx.people)
    c2 = build_candidates(fx.events, fx.goals, fx.people)
    p1, p2 = optimize(c1), optimize(c2)
    assert p1.model_dump() == p2.model_dump()
    lines = explain(p1)
    assert any(line.startswith("KEEP") for line in lines)
    assert any(line.startswith("SKIP") for line in lines)


def test_optimize_accepts_raw_events():
    plan = optimize([ev("a", at(28, 9), at(28, 10))])
    assert plan.rejected or plan.items  # utility 0 without goals: rejected, not crashing
