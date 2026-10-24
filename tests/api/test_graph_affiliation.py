"""The API graph must not turn event candidates into confirmed affiliations."""

from __future__ import annotations

import pytest

from conferge.api import logic
from conferge.api.data import load_fixture
from conferge.core.schemas import Event


@pytest.mark.parametrize("relation", ["official", "confirmed_side_event", "candidate", "unrelated", "unknown"])
@pytest.mark.parametrize("conference_id", ["github-universe-2026", "another-conference", None])
def test_graph_only_links_confirmed_events_to_their_conference(
    relation: str, conference_id: str | None,
) -> None:
    data = load_fixture()
    payload = data.events[0].model_dump()
    payload.update(
        conference_id=conference_id,
        conference_relation=relation,
        relation_evidence=["fixture:affiliation-evidence"] if relation in {"official", "confirmed_side_event"} else [],
    )
    event = Event.model_validate(payload)
    data.events = [event]

    graph = logic.build_graph(data, logic.parse_goals(data.demo_goal_text))
    affiliations = [edge for edge in graph["edges"] if edge["type"] == "PART_OF"]

    if conference_id == data.conference.id and relation in {"official", "confirmed_side_event"}:
        assert [(edge["source"], edge["target"]) for edge in affiliations] == [(event.id, data.conference.id)]
    else:
        assert affiliations == []
    assert any(node["id"] == event.id for node in graph["nodes"])
