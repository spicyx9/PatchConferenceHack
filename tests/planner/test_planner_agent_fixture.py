"""PlannerAgent on fixtures/planner.json: regression vs frozen "expected" and invariants."""

from __future__ import annotations

import random

import pytest
from planner_helpers import load_fixture, make_ctx, plan_of, ranking, raw_context, rejected_map, run_planner

from conferge.agents.planner.candidates import World
from conferge.core.schemas import AgentContext, AgentResult

EXPECTED = load_fixture()["expected"]


@pytest.fixture()
async def result() -> AgentResult:
    return await run_planner(make_ctx())


def _opp(result: AgentResult, person_id: str):  # type: ignore[no-untyped-def]
    return next(o for o in result.opportunities if o.person_ids == [person_id])


async def test_status_and_mode(result: AgentResult) -> None:
    assert result.status == "ok"
    assert result.source_mode == "fixture"
    assert result.errors == []
    assert result.agent == "planner-w09"


async def test_people_ranking_matches_expected(result: AgentResult) -> None:
    assert ranking(result) == EXPECTED["people_ranking"]
    scores = [o.score for o in result.opportunities]
    assert scores == sorted(scores, reverse=True)


async def test_presence_matches_expected(result: AgentResult) -> None:
    assert {o.person_ids[0]: o.presence for o in result.opportunities} == EXPECTED["presence"]


async def test_plan_days_match_expected(result: AgentResult) -> None:
    days = [{"date": d["date"], "event_ids": [i["id"] for i in d["items"]]}
            for d in plan_of(result)["days"]]
    assert days == EXPECTED["plan"]["days"]


async def test_rejected_match_expected(result: AgentResult) -> None:
    assert rejected_map(result) == EXPECTED["plan"]["rejected"]


async def test_decision_layout(result: AgentResult) -> None:
    assert result.decisions[0]["type"] == "plan"
    scored = [d["event_id"] for d in result.decisions if d["type"] == "event_score"]
    assert sorted(scored) == sorted(e.id for e in make_ctx().events)
    for d in result.decisions:
        if d["type"] == "event_score":
            assert 0 <= d["score"] <= 100
            assert set("GPSNTCR") <= set(d["terms"])


@pytest.mark.parametrize("seed", [0, 1, 7, 42, 2026])
async def test_ranking_and_plan_stable_under_shuffle(seed: int, result: AgentResult) -> None:
    raw = raw_context()
    rng = random.Random(seed)
    rng.shuffle(raw["people"])
    rng.shuffle(raw["events"])
    shuffled = await run_planner(make_ctx(raw))
    assert ranking(shuffled) == ranking(result)
    assert [o.score for o in shuffled.opportunities] == [o.score for o in result.opportunities]
    assert _days_without_reason(shuffled) == _days_without_reason(result)
    assert rejected_map(shuffled) == rejected_map(result)
    assert [o.rationale for o in shuffled.opportunities] == [
        o.rationale for o in result.opportunities]


def _days_without_reason(result: AgentResult) -> list[list[dict[str, object]]]:
    return [[{k: v for k, v in item.items() if k != "reason"} for item in day["items"]]
            for day in plan_of(result)["days"]]


async def test_event_explanations_stable_under_shuffle(result: AgentResult) -> None:
    raw = raw_context()
    random.Random(7).shuffle(raw["people"])
    shuffled = await run_planner(make_ctx(raw))
    def explanations(res: AgentResult) -> list[str]:
        return [d["explanation"] for d in res.decisions if d.get("type") == "event_score"]
    assert explanations(shuffled) == explanations(result)
    assert plan_of(shuffled)["days"] == plan_of(result)["days"]


def test_speaker_not_confirmed_at_side_event() -> None:
    ctx = make_ctx()
    world = World(ctx)
    bo = world.people["fx-p-inv-bo"]
    assert world.presence(bo, world.events["fx-s-seed-panel"])[0] == "confirmed"
    assert world.presence(bo, world.events["fx-side-agents-night"])[0] == "probable"


async def test_goals_in_context_skip_parsing() -> None:
    from conferge.agents.planner.goals import parse_goals

    raw = raw_context()
    raw["goals"] = [g.model_dump(mode="json") for g in parse_goals(load_fixture()["goal_text"])]
    res = await run_planner(AgentContext.model_validate(raw))
    assert ranking(res) == EXPECTED["people_ranking"]
    assert not any("no goals in context" in e for e in res.explanations)
