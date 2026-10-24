"""Follow-up drafts: built from the meeting facts only, proposed, never sent."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from conferge.agents.followup import FollowUpAgent, best_goal, draft_followup
from conferge.api import logic
from conferge.api.app import create_app
from conferge.api.data import load_fixture
from conferge.api.providers import Providers
from conferge.core.schemas import AgentContext

MET_AT = datetime(2026, 10, 28, 18, 30, tzinfo=timezone.utc)


@pytest.fixture()
def client() -> TestClient:
    return TestClient(create_app(found=Providers(), graph_probe=False))


def _data():  # type: ignore[no-untyped-def]
    data = load_fixture()
    goals = logic.parse_goals(data.demo_goal_text)
    return data, goals


def test_draft_uses_goal_event_company_and_quotes_the_note() -> None:
    data, goals = _data()
    person = data.person("p-inv-ada")
    assert person is not None
    goal = best_goal(person, goals)
    assert goal is not None and goal.id == "goal-seed-investors"
    event = data.event(person.event_ids[0])
    draft = draft_followup(
        person,
        conference=data.conference,
        goal=goal,
        event=event,
        company=data.company(person.company_id),
        note="talked about seed",
        met_at=MET_AT,
    )
    assert draft.sent is False and draft.status == "draft"
    assert draft.message.startswith("Hi Ada,")
    assert event is not None and event.title in draft.message
    assert "[Your note from the meeting, edit before sending: talked about seed]" in draft.message
    assert "short deck" in draft.message  # investor ask
    assert draft.based_on["goal"] == goal.description
    assert draft.based_on["shared_topic"] in person.topics
    assert draft.next_action.kind == "public_profile_message"
    assert draft.next_action.due_at == datetime(2026, 10, 30, 18, 30, tzinfo=timezone.utc)
    assert "fixture person" in " ".join(draft.warnings)


def test_draft_without_note_or_goal_is_flagged_not_invented() -> None:
    data, _ = _data()
    person = data.person("p-fnd-elin")
    assert person is not None
    draft = draft_followup(person, conference=data.conference, goal=None, met_at=MET_AT)
    assert "[Your note" not in draft.message
    assert "no meeting note" in " ".join(draft.warnings)
    assert "no goal matched" in " ".join(draft.warnings)
    assert (
        data.conference.name in draft.message
    )  # falls back to the conference, never a made-up event


def test_naive_met_at_is_refused() -> None:
    data, _ = _data()
    person = data.person("p-inv-ada")
    assert person is not None
    with pytest.raises(ValueError):
        draft_followup(person, conference=data.conference, goal=None, met_at=datetime(2026, 10, 28))


async def test_agent_one_draft_per_met_person() -> None:
    data, goals = _data()
    ctx = AgentContext(
        conference=data.conference,
        goals=goals,
        events=data.events,
        people=data.people,
        constraints={
            "met_person_ids": ["p-inv-ada", "p-fnd-elin", "ghost"],
            "met_notes": {"p-inv-ada": "coffee"},
        },
    )
    res = await FollowUpAgent().run(ctx)
    assert res.status == "ok" and res.agent == "followup"
    drafts = [d for d in res.decisions if d["type"] == "followup_draft"]
    assert [d["person_id"] for d in drafts] == ["p-inv-ada", "p-fnd-elin"]
    assert all(d["sent"] is False for d in drafts)
    assert "coffee" in drafts[0]["message"] and "[Your note" not in drafts[1]["message"]
    empty = await FollowUpAgent().run(ctx.model_copy(update={"constraints": {}}))
    assert empty.status == "degraded" and not empty.decisions


def test_api_followup_requires_a_recorded_meeting(client: TestClient) -> None:
    top = client.get("/api/v1/people").json()["items"][0]["person"]["id"]
    assert client.get("/api/v1/followup", params={"person": top}).status_code == 409
    assert client.get("/api/v1/followup", params={"person": "nobody"}).status_code == 404
    client.post("/api/v1/met", json={"person_id": top, "note": "talked about seed"})
    body = client.get("/api/v1/followup", params={"person": top}).json()
    assert body["person_id"] == top and body["sent"] is False
    assert "talked about seed" in body["message"]
    assert body["based_on"]["path"]  # rationale of the ranking that justified the meeting
    assert body["next_action"]["due_at"] > body["based_on"]["met_at"]
    assert body["data_source"] == "fixture"
