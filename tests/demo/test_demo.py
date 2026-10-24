"""Offline tests for window 13: deterministic replay, labels, no unstated real data."""

from __future__ import annotations

import json
import socket
from decimal import Decimal

import pytest

from conferge.core.contracts import Agent
from conferge.core.schemas import AgentContext
from conferge.demo import DemoPlannerAgent, build_world, replay
from conferge.demo.__main__ import render
from conferge.demo.engine import apply_change, build_plan, score_person
from conferge.demo.fixture import (
    FIXTURE_PATH,
    build_fixture,
    dumps,
    load_fixture,
    world_from_fixture,
)

DOMAINS = ("companies", "people", "events", "lodging", "flights")


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def guard(*args, **kwargs):
        raise AssertionError("demo must not touch the network")

    monkeypatch.setattr(socket, "create_connection", guard)
    monkeypatch.setattr(socket.socket, "connect", guard)


def test_committed_fixture_is_up_to_date():
    assert FIXTURE_PATH.read_text(encoding="utf-8") == dumps(build_fixture())


def test_build_is_deterministic():
    assert dumps(build_fixture()) == dumps(build_fixture())
    assert replay() == replay()


def test_replay_from_file_matches_expected():
    parsed = load_fixture()
    assert json.loads(json.dumps(replay(world_from_fixture()))) == parsed["expected_replay"]


def test_every_record_and_evidence_is_fixture():
    data = load_fixture()
    assert data["source_mode"] == "fixture"
    assert data["user"]["source_mode"] == "fixture"
    assert all(e.source_mode == "fixture" for e in data["conference"].evidence)
    for key in DOMAINS:
        env = data[key]
        assert env.source_mode == "fixture"
        assert all(r.source_mode == "fixture" and r.termination == "not_applicable"
                   for r in env.reports)
        for item in env.items:
            assert item.evidence, f"{item.id} has no evidence"
            for ev in item.evidence:
                assert ev.source_mode == "fixture"
                assert ev.collected_at is not None and ev.collected_at.tzinfo is not None


def test_no_unstated_real_data():
    raw = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    assert "fictional" in raw["disclaimer"].lower()
    data = load_fixture()
    for person in data["people"].items:
        assert person.bio and person.bio.startswith("Fictional demo persona")
        assert person.linkedin_url is None and person.github_url is None
        assert person.x_handle is None
    for company in data["companies"].items:
        assert "fictional-demo" in company.categories
        assert company.domain is None and company.linkedin_url is None
    # Only the anchor conference may point to a real site; everything else is .invalid.
    urls = []

    def walk(node, path):
        if isinstance(node, dict):
            for k, v in node.items():
                walk(v, f"{path}.{k}")
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, f"{path}[{i}]")
        elif isinstance(node, str) and node.startswith("http"):
            urls.append((path, node))

    walk(raw, "$")
    real = [(p, u) for p, u in urls if ".invalid/" not in u]
    assert real == [("$.conference.official_url", "https://githubuniverse.com/")]


def test_simulated_prices_are_never_claimed_verified():
    w = build_world()
    for stay in w.lodging:
        assert stay.price_status in {"quoted_total", "indicative"}
        assert stay.availability == "unknown" and stay.verified_at is None
        assert stay.taxes is None and stay.fees_total is None  # unknown stays unknown
    for offer in w.flights:
        assert offer.price_status == "sandbox"
        assert isinstance(offer.total_price, str)
        assert offer.baggage_verified is None
        assert any("Simulated" in warning for warning in offer.warnings)


def test_side_events_are_only_candidates_and_times_are_aware():
    for event in build_world().events:
        assert event.start_at.tzinfo is not None and event.end_at.tzinfo is not None
        assert event.timezone == "America/Los_Angeles"
        if event.event_type != "session":
            assert event.conference_relation == "candidate"
            assert event.registered_count is None and event.capacity is None
            assert event.is_free is None and event.price_min is None


def test_goal_weights_and_scoring():
    w = build_world()
    assert [g.priority for g in w.goals] == [0.45, 0.35, 0.20]
    scores = {p.id: score_person(p, w.goals)[0] for p in w.people}
    assert scores["p-exe-nils"] == 0 and scores["p-dr-mara"] == 0
    assert max(scores, key=lambda k: (scores[k], k)) == "p-inv-ada"


def test_clash_on_oct_28_evening_is_explained():
    r = replay()
    clashes = r["plan"]["clashes"]
    assert len(clashes) == 1
    clash = clashes[0]
    assert clash["event_ids"] == ["evt-side-agents-after-hours", "evt-side-devtools-dinner"]
    assert clash["winner"] == "evt-side-agents-after-hours"
    assert clash["missed_people"] == ["p-inv-cleo", "p-pm-kael"]
    assert 1.0 < clash["distance_km"] < 2.0
    plan_ids = [e["id"] for e in r["plan"]["events"]]
    assert "evt-side-devtools-dinner" not in plan_ids


def test_plan_has_no_overlaps():
    w = build_world()
    plan = build_plan(w.events, w.people, w.goals)["events"]
    for a, b in zip(plan, plan[1:], strict=False):
        assert a["end_at"] <= b["start_at"]


def test_cancellation_triggers_replan_and_ranking_change():
    r = replay()
    assert r["diff"]["removed"] == ["evt-side-agents-after-hours"]
    assert r["diff"]["added"] == ["evt-side-devtools-dinner"]
    assert "evt-side-agents-after-hours" in r["replan"]["excluded"]
    before = [p["id"] for p in r["top_people"]]
    assert before.index("p-inv-bram") < r["top_people_after"].index("p-inv-bram")
    assert "p-fnd-hale" not in r["top_people_after"]


def test_apply_change_rejects_unknown_input():
    w = build_world()
    with pytest.raises(ValueError):
        apply_change(w.events, {"type": "cancelled", "event_id": "nope"})
    with pytest.raises(ValueError):
        apply_change(w.events, {"type": "teleported", "event_id": w.events[0].id})


def test_travel_respects_arrival_and_budget():
    t = replay()["travel"]
    assert t["flight_id"] == "flt-ewr-sfo-noon"
    assert t["rejected_flights"] == ["flt-lga-oak-evening"]  # lands after the meetup
    assert Decimal(t["simulated_total_usd"]) <= Decimal(t["budget_usd"])
    assert t["label"].startswith("fixture")


async def test_agent_protocol_and_labels():
    w = build_world()
    agent = DemoPlannerAgent()
    assert isinstance(agent, Agent)
    ctx = AgentContext(conference=w.conference, goals=w.goals, data_mode="fixture",
                       events=w.events, people=w.people,
                       constraints={"changes": [{"type": "sold_out",
                                                 "event_id": "evt-side-agents-after-hours"}]})
    result = await agent.run(ctx)
    assert result.status == "ok" and result.source_mode == "fixture"
    assert result.opportunities and all(
        any(w.startswith("fixture") for w in o.warnings) for o in result.opportunities
    )
    assert any("not live" in e for e in result.explanations)
    plan_ids = [e["id"] for e in result.decisions[0]["events"]]
    assert "evt-side-devtools-dinner" in plan_ids


async def test_agent_fails_visibly_without_events():
    w = build_world()
    result = await DemoPlannerAgent().run(AgentContext(conference=w.conference, goals=w.goals))
    assert result.status == "failed" and result.errors


def test_cli_render_labels_fixture():
    text = render(replay())
    assert text.startswith("[FIXTURE]")
    assert "sandbox" in text and "Devtools Founders Dinner" in text
