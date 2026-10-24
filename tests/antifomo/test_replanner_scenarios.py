from __future__ import annotations

import importlib
from datetime import datetime

import pytest
from w10_helpers import at

from conferge.agents.antifomo import optimize
from conferge.agents.antifomo.fixture import load_fixture
from conferge.agents.antifomo.models import Constraints, Plan
from conferge.agents.antifomo.travel import fits_before
from conferge.agents.replanner import (
    Change, apply_change, diff, list_scenarios, replan, run_scenario, state_from_fixture,
)
from conferge.core.schemas import AgentContext, AgentResult
from conferge.core.store import GraphStore


def _no_overlap(plan_dump, state):
    plan = Plan.model_validate(plan_dump)
    events = {e.id: e for e in state.events}
    by_day: dict[str, list] = {}
    for i in plan.items:
        by_day.setdefault(i.day, []).append(i)
    for items in by_day.values():
        items.sort(key=lambda i: i.start_at)
        for a, b in zip(items, items[1:], strict=False):
            assert fits_before(events[a.event_id], events[b.event_id], state.constraints)


def test_list_scenarios():
    ids = [s["id"] for s in list_scenarios()]
    assert ids == ["sold-out-evening", "new-event-two-targets", "talk-moved-conflict"]


def test_sold_out_scenario_minimal():
    r = run_scenario("sold-out-evening")
    assert r["source_mode"] == "fixture"
    assert r["diff"]["changes"] <= 2
    assert "ev-28-investors-happy-hour" in [x["event_id"] for x in r["diff"]["removed"]]
    assert "ev-28-investors-happy-hour" not in [i["event_id"] for i in r["after"]["items"]]


def test_new_event_scenario_adds_breakfast():
    r = run_scenario("new-event-two-targets")
    assert "ev-29-agents-investors-breakfast" in [x["event_id"] for x in r["diff"]["added"]]
    assert r["diff"]["changes"] <= 2


def test_talk_moved_scenario():
    r = run_scenario("talk-moved-conflict")
    assert "ev-28-mcp-talk" in [x["event_id"] for x in r["diff"]["moved"]]
    fx = load_fixture()
    state = state_from_fixture(fx)
    moved = apply_change(state, Change(type="time_change", event_id="ev-28-mcp-talk",
                                       start_at=at(28, 14, 30), end_at=at(28, 15, 15))).state
    _no_overlap(r["after"], moved)


def test_unknown_scenario_raises():
    with pytest.raises(KeyError):
        run_scenario("nope")


def _state():
    return state_from_fixture(load_fixture())


def test_apply_change_does_not_mutate_and_validates():
    state = _state()
    snapshot = state.model_dump()
    res = apply_change(state, Change(type="sold_out", event_id="ev-28-keynote"))
    assert state.model_dump() == snapshot
    assert res.state.event("ev-28-keynote").status == "sold_out"
    with pytest.raises(ValueError):
        apply_change(state, Change(type="cancelled", event_id="missing"))


def test_meeting_accepted_blocks_slot():
    from conferge.agents.antifomo.models import TimeSlot
    state = _state()
    before = optimize(state.candidates(), state.constraints)
    assert "ev-28-keynote" in before.event_ids
    slot = TimeSlot(id="m1", label="Coffee with VC", start=at(28, 9, 30), end=at(28, 10))
    res = apply_change(state, Change(type="meeting_accepted", slot=slot))
    after = replan(before, res.state)
    assert "ev-28-keynote" not in after.event_ids
    assert after.rejection("ev-28-keynote").code == "blocked_slot"


def test_user_skipped_and_new_contact_met_and_presence():
    state = _state()
    res = apply_change(state, Change(type="user_skipped", event_id="ev-28-keynote"))
    assert "ev-28-keynote" in res.state.constraints.excluded_event_ids
    res2 = apply_change(state, Change(type="new_contact_met", person_id="p-inv-ben"))
    hh = next(c for c in res2.state.candidates() if c.id == "ev-28-investors-happy-hour")
    assert "p-inv-ben" not in hh.targets_confirmed
    before = next(c for c in state.candidates() if c.id == "ev-28-eval-workshop")
    res3 = apply_change(state, Change(type="person_target_available", event_id="ev-28-eval-workshop",
                                      person_id="p-inv-ava", presence="confirmed"))
    after = next(c for c in res3.state.candidates() if c.id == "ev-28-eval-workshop")
    assert "p-inv-ava" in after.targets_confirmed
    assert after.utility > before.utility


class FakeGraph:
    def __init__(self, fail=False):
        self.calls = []
        self.fail = fail

    def query(self, q, params=None):
        if self.fail:
            raise ConnectionError("down")
        self.calls.append((q, params))


def test_graph_writes_via_store_and_failures_are_errors():
    state = _state()
    g = FakeGraph()
    res = apply_change(state, Change(type="sold_out", event_id="ev-28-keynote",
                                     observed_at=datetime.fromisoformat("2026-10-24T12:00:00-07:00")),
                       GraphStore(g))
    assert res.graph_writes and g.calls
    assert g.calls[0][0].startswith("MERGE (n:Event")
    bad = apply_change(state, Change(type="new_contact_met", person_id="p-inv-ben"),
                       GraphStore(FakeGraph(fail=True)))
    assert bad.errors and not bad.graph_writes


def test_diff_identical_plans():
    state = _state()
    p = optimize(state.candidates(), state.constraints)
    d = diff(p, p)
    assert d.changes == 0 and not d.added and not d.removed and not d.moved
    assert any("No change" in r for r in d.reasons)


def _ctx(**constraints):
    fx = load_fixture()
    return AgentContext(conference=fx.conference, goals=fx.goals, data_mode="fixture",
                        events=fx.events, people=fx.people, constraints=constraints)


async def test_antifomo_agent_run():
    import conferge.agents.antifomo as antifomo
    res = await antifomo.run(_ctx())
    assert isinstance(res, AgentResult) and res.status == "ok"
    assert res.source_mode == "fixture"
    assert res.opportunities and all(o.event_id for o in res.opportunities)
    assert any(d["type"] == "verdict" for d in res.decisions)


async def test_replanner_agent_run_variants():
    import conferge.agents.replanner as replanner
    ok = await replanner.run(_ctx(scenario_id="sold-out-evening"))
    assert ok.status == "ok" and ok.source_mode == "fixture"
    failed = await replanner.run(_ctx())
    assert failed.status == "failed"
    res = await replanner.run(_ctx(change={"type": "sold_out",
                                           "event_id": "ev-28-investors-happy-hour"}))
    assert res.status == "ok"
    assert res.decisions[0]["type"] == "diff"
    bad = await replanner.run(_ctx(change={"type": "sold_out", "event_id": "missing"}))
    assert bad.status == "failed"


def test_api_resolver_finds_agents():
    from conferge.api.providers import _resolve_agent
    for name in ("conferge.agents.antifomo", "conferge.agents.replanner"):
        assert callable(_resolve_agent(importlib.import_module(name)))


def test_constraints_default_timezone():
    assert Constraints().timezone == "America/Los_Angeles"
