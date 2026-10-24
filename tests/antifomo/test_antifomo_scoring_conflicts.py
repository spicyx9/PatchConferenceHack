from __future__ import annotations

from w10_helpers import at, ev

from conferge.agents.antifomo import build_candidates, find_conflicts, score_event, verdicts
from conferge.agents.antifomo.fixture import load_fixture
from conferge.core.schemas import Goal, Opportunity, Person

GOALS = [Goal(id="g", description="seed investors", topics=["AI agents"], target_roles=["investor"])]


def person(pid, **kw):
    return Person(id=pid, name=pid, roles=["investor"], **kw)


def test_presence_only_from_evidence():
    e = ev("e", at(28, 9), at(28, 10), speaker_ids=["spk"], organizer_ids=["org"],
           topics=["AI agents"])
    people = [
        person("spk"), person("org"),
        person("listed", participation="public_attendee_listing", event_ids=["e"]),
        person("other_speaker", participation="confirmed_speaker", event_ids=["elsewhere"]),
        person("candidate", participation="relevant_candidate", event_ids=["e"]),
    ]
    c = score_event(e, GOALS, people)
    assert c.targets_confirmed == ["org", "spk"]
    assert c.targets_probable == ["listed"]


def test_met_people_excluded_and_overrides():
    e = ev("e", at(28, 9), at(28, 10), speaker_ids=["spk"])
    people = [person("spk"), person("p2")]
    assert score_event(e, GOALS, people, met={"spk"}).targets_confirmed == []
    c = score_event(e, GOALS, people, overrides={"e": {"p2": "confirmed"}})
    assert c.targets_confirmed == ["p2", "spk"]


def test_planner_opportunity_overrides_utility():
    e = ev("e", at(28, 9), at(28, 10))
    opp = Opportunity(id="o", title="t", goal_ids=["g"], event_id="e", score=77, rationale="r")
    [c] = build_candidates([e], GOALS, [], [opp])
    assert c.utility == 77 and c.score_source == "planner_opportunity"


def test_fixture_conflicts_and_verdict():
    fx = load_fixture()
    cands = build_candidates(fx.events, fx.goals, fx.people)
    pairs = {(k.a, k.b) for k in find_conflicts(cands)}
    assert ("ev-28-devtools-panel", "ev-28-mcp-talk") in pairs
    assert ("ev-28-founders-mixer", "ev-28-investors-happy-hour") in pairs
    found = verdicts(cands, fx.people)
    v = next(x for x in found if {x.a, x.b} == {"ev-28-founders-mixer",
                                               "ev-28-investors-happy-hour"})
    assert v.chosen == "ev-28-investors-happy-hour"
    assert v.margin > 0
    assert any("Eli" in m for m in v.missed)
    assert v.alternative and v.alternative.event_id == "ev-28-late-party"
    assert "Eli" in v.text


def test_verdicts_deterministic():
    fx = load_fixture()
    a = verdicts(build_candidates(fx.events, fx.goals, fx.people), fx.people)
    b = verdicts(build_candidates(fx.events, fx.goals, fx.people), fx.people)
    assert [x.model_dump() for x in a] == [x.model_dump() for x in b]


def test_fixture_is_labelled():
    fx = load_fixture()
    for e in fx.events:
        assert e.title.startswith("[Fixture]")
        assert e.evidence and all(x.source_mode == "fixture" and x.collected_at for x in e.evidence)
    for p in fx.people:
        assert p.evidence and all(x.source_mode == "fixture" and x.collected_at for x in p.evidence)
