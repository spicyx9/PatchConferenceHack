import pytest
from people_testkit import profile

from conferge.core.schemas import AgentContext, Conference
from conferge.people.agent import PeopleAgent, profiles_from_people
from conferge.people.match import (
    GraphAdjustment,
    LLMScore,
    apply_graph_adjustments,
    goal_fit,
    rank,
    run,
    shortlist,
)


def _people():
    return [
        profile("p:founder", "Avery Example", title="Co-founder", roles=["founder"],
                topics=["ai agents", "mcp"], company_name="Example Labs",
                presences=[("ev-talk", "speaker", "confirmed")]),
        profile("p:pm", "Blake Sample", roles=["pm"], topics=["copilot"],
                presences=[("ev-party", "host", "confirmed")]),
        profile("p:cand", "Casey Placeholder", roles=["founder"], topics=["ai agents"]),
        profile("p:none", "Drew Nobody", roles=["engineer"], topics=["infra"]),
    ]


def test_goal_fit_and_shortlist(goals):
    fit, hits = goal_fit(_people()[0], goals[1])
    assert fit == pytest.approx(1.0) and hits == ["founder", "ai agents", "mcp"]
    ids = [p.id for p, _, _ in shortlist(_people(), goals)]
    assert "p:none" not in ids  # no shared role/topic
    assert ids[0] == "p:founder"
    assert len(shortlist(_people(), goals, size=1)) == 1


@pytest.mark.asyncio
async def test_rank_deterministic_where_presence_opener(goals, events):
    matches, warnings = await rank(goals, _people(), events=events)
    by_id = {m.person.id: m for m in matches}
    top = by_id["p:founder"]
    assert top.scorer == "deterministic" and top.presence_status == "confirmed"
    assert top.where[0].start_at is not None and top.where[0].venue == "Fort Mason Pavilion"
    assert "Agents in production" in top.opener and "Example Labs" in top.opener
    host = by_id["p:pm"]
    assert host.where[0].start_at is None  # unknown stays unknown
    assert host.person.participation == "confirmed_organizer"
    cand = by_id["p:cand"]
    assert cand.presence_status == "unknown" and cand.where == []
    assert cand.person.participation == "unknown"
    assert any("Relevant candidate only" in r for r in cand.reasons)
    assert top.score > cand.score
    assert not warnings


@pytest.mark.asyncio
async def test_llm_scorer_capped_and_fallback(goals, events):
    calls = []

    class Fake:
        async def score(self, prof, gs):
            calls.append(prof.id)
            return LLMScore(goal_scores={"g-pm": 5.0}, reason="LLM says relevant",
                            opener="Hello from LLM")

    matches, _ = await rank(goals, _people(), events=events, scorer=Fake(), llm_cap=1)
    assert len(calls) == 1
    llm = [m for m in matches if m.scorer == "llm"]
    assert len(llm) == 1 and llm[0].goal_scores["g-pm"] == 1.0  # clipped
    assert llm[0].opener == "Hello from LLM"

    class Boom:
        async def score(self, prof, gs):
            raise TimeoutError

    result = await run(goals, _people(), events=events, scorer=Boom())
    assert result.status == "degraded" and result.scorer == "deterministic"
    assert all(m.warnings for m in result.matches[:3])


@pytest.mark.asyncio
async def test_run_modes_and_empty(goals):
    res = await run(goals, _people())
    assert res.source_mode == "fixture" and res.status == "ok"
    empty = await run(goals, [])
    assert empty.status == "failed" and empty.matches == []


@pytest.mark.asyncio
async def test_apply_graph_adjustments_is_pure(goals, events):
    matches, _ = await rank(goals, _people(), events=events)
    before = [(m.person.id, m.score) for m in matches]
    adjusted = apply_graph_adjustments(matches, {
        "p:founder": GraphAdjustment(-100, "already MET"),
        "p:cand": [GraphAdjustment(5, "2-hop path to goal")],
    })
    assert [(m.person.id, m.score) for m in matches] == before
    assert adjusted[-1].person.id == "p:founder" and adjusted[-1].score == 0
    assert any("already MET" in r for r in adjusted[-1].reasons)


@pytest.mark.asyncio
async def test_agent_contract(goals, events):
    conf = Conference(id="github-universe-2026", name="GitHub Universe 2026",
                      start_date="2026-10-28", end_date="2026-10-29", city="San Francisco",
                      timezone="America/Los_Angeles")
    people = [p.to_person() for p in _people()]
    res = await PeopleAgent().run(AgentContext(conference=conf, goals=goals, people=people,
                                               events=events, data_mode="fixture"))
    assert res.status == "ok" and res.source_mode == "fixture"
    opp = {o.person_ids[0]: o for o in res.opportunities}
    assert opp["p:founder"].presence == "confirmed"
    assert "Fort Mason Pavilion" in opp["p:founder"].where
    assert opp["p:cand"].presence == "unknown" and opp["p:cand"].where is None
    empty = await PeopleAgent().run(AgentContext(conference=conf, goals=goals))
    assert empty.status == "failed"
    # Only speaker/organizer participation becomes a confirmed presence.
    assert all(p.status == "confirmed" for x in profiles_from_people(people)
               for p in x.presences)
