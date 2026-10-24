"""Goal parsing: French/English demo text, guardrail defaults, counts, weights."""

from __future__ import annotations

import pytest
from planner_helpers import FRENCH_DEMO, load_fixture

from conferge.agents.planner.goals import DEFAULT_GOALS, normalized_weights, parse_goals
from conferge.core.schemas import Goal


@pytest.mark.parametrize("text", [FRENCH_DEMO, load_fixture()["goal_text"]])
def test_demo_texts_give_three_weighted_goals(text: str) -> None:
    goals = parse_goals(text)
    assert len(goals) == 3
    assert [g.target_roles for g in goals] == [["investor"], ["founder"], ["pm"]]
    assert [g.priority for g in goals] == pytest.approx([0.45, 0.35, 0.20])
    assert sum(g.priority for g in goals) == pytest.approx(1.0)
    assert all(not t.startswith("default") for g in goals for t in g.tags)
    assert goals[0].id == "goal-seed-investors"
    assert "seed" in goals[0].description


def test_french_topics_follow_each_clause() -> None:
    goals = parse_goals(FRENCH_DEMO)
    assert "ai agents" in goals[1].topics
    assert "copilot" in goals[2].topics


def test_user_profile_before_trigger_is_not_a_goal() -> None:
    # "Fondateur" describes the user; only the founders after "rencontrer" count.
    goals = parse_goals("Fondateur d'un outil dev IA, je veux rencontrer des investisseurs seed.")
    assert [g.target_roles for g in goals] == [["investor"]]
    goals = parse_goals("Founder of a dev tool, here to meet Copilot PMs.")
    assert [g.target_roles for g in goals] == [["pm"]]


def test_fixture_expected_goal_ids_and_weights() -> None:
    fx = load_fixture()
    goals = parse_goals(fx["goal_text"])
    assert [g.id for g in goals] == fx["expected"]["goal_ids"]
    assert [g.priority for g in goals] == pytest.approx(fx["expected"]["goal_weights"])


@pytest.mark.parametrize("text", [None, "", "   ", "!!! ,,, ;;", "lorem ipsum dolor sit amet"])
def test_empty_or_garbage_text_gives_tagged_defaults(text: str | None) -> None:
    goals = parse_goals(text)
    assert [g.id for g in goals] == [g.id for g in DEFAULT_GOALS]
    assert all(g.tags and g.tags[0].startswith("default:") for g in goals)
    assert sum(g.priority for g in goals) == pytest.approx(1.0)


def test_defaults_are_copies_not_shared_objects() -> None:
    goals = parse_goals(None)
    goals[0].topics.append("mutated")
    assert "mutated" not in DEFAULT_GOALS[0].topics


def test_target_count_is_read() -> None:
    goals = parse_goals("meet 5 seed investors")
    assert len(goals) == 1
    assert goals[0].target_roles == ["investor"]
    assert goals[0].target_count == 5
    assert goals[0].priority == pytest.approx(1.0)


def test_parse_is_deterministic() -> None:
    first = [g.model_dump() for g in parse_goals(FRENCH_DEMO)]
    second = [g.model_dump() for g in parse_goals(FRENCH_DEMO)]
    assert first == second


def test_at_most_five_goals_and_weights_sum_to_one() -> None:
    text = "meet investors, founders, PMs, engineers, developer advocates and executives"
    goals = parse_goals(text)
    assert 1 <= len(goals) <= 5
    assert sum(g.priority for g in goals) == pytest.approx(1.0)
    assert len({g.id for g in goals}) == len(goals)


def test_normalized_weights_rescale() -> None:
    goals = [
        Goal(id="a", description="a", priority=1.0),
        Goal(id="b", description="b", priority=0.5),
        Goal(id="c", description="c", priority=0.5),
    ]
    weights = normalized_weights(goals)
    assert weights == pytest.approx({"a": 0.5, "b": 0.25, "c": 0.25})
    assert sum(weights.values()) == pytest.approx(1.0)


def test_normalized_weights_zero_and_empty() -> None:
    goals = [Goal(id="a", description="a", priority=0.0), Goal(id="b", description="b", priority=0.0)]
    assert normalized_weights(goals) == pytest.approx({"a": 0.5, "b": 0.5})
    assert normalized_weights([]) == {}


def test_self_description_without_trigger_is_not_a_goal() -> None:
    from conferge.agents.planner.goals import parse_goals as parse

    assert all(g.tags[0].startswith("default") for g in parse("I am a founder"))
    goals = parse("I am a founder, looking for seed investors and Copilot PMs")
    assert [g.target_roles for g in goals] == [["investor"], ["pm"]]
