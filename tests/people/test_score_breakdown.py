"""Corroboration bonus, score breakdown and grade on PersonMatch."""

from __future__ import annotations

import asyncio

import pytest
from people_testkit import evidence, profile

from conferge.people.match import GraphAdjustment, apply_graph_adjustments, breakdown, rank
from conferge.people.models import Presence, ScoreBreakdown, grade_for


def _with_sources(*providers: str):
    base = profile("p1", "Avery Example", roles=["investor"], topics=["developer tools"],
                   presences=[("ev-talk", "speaker", "confirmed")])
    person = base.person.model_copy(update={"evidence": [evidence(p) for p in providers]})
    return base.model_copy(update={"person": person, "presences": [Presence(
        event_id="ev-talk", kind="speaker", status="confirmed", evidence=evidence(providers[0]))]})


@pytest.mark.parametrize(("providers", "bonus"), [
    (("a",), 0.0), (("a", "a"), 0.0), (("a", "b"), 4.0), (("a", "b", "c"), 6.0),
    (("a", "b", "c", "d"), 6.0)])
def test_corroboration_counts_distinct_providers(providers, bonus):
    parts = breakdown({"g": 0.5}, {"g": 1.0}, _with_sources(*providers))
    assert parts.corroboration == bonus
    assert parts.goal_fit == 40.0 and parts.presence == 12.0


def test_breakdown_is_capped_at_100_and_still_sums():
    full = _with_sources("a", "b", "c")
    person = full.person.model_copy(update={
        "identity_confidence": 0.95, "linkedin_url": "https://www.linkedin.com/in/avery-example/"})
    parts = breakdown({"g": 1.0}, {"g": 1.0}, full.model_copy(update={"person": person}))
    # 80 + 12 + 8 + 6 = 106: the cap trims the last parts, the sum is exactly 100.
    assert parts == ScoreBreakdown(goal_fit=80.0, presence=12.0, identity=8.0, corroboration=0.0)
    assert parts.total() == 100.0


def test_capped_trims_in_field_order_and_rounds_exactly():
    parts = ScoreBreakdown.capped({"goal_fit": 90.0, "presence": 12.0, "corroboration": 4.0})
    assert parts == ScoreBreakdown(goal_fit=90.0, presence=10.0)
    thirds = ScoreBreakdown.capped({"goal_fit": 10 / 3, "presence": 10 / 3, "identity": 10 / 3})
    assert thirds.total() == 10.0


@pytest.mark.parametrize(("score", "grade"), [
    (100, "A"), (80, "A"), (79.99, "B"), (65, "B"), (64.9, "C"), (50, "C"), (49.99, "D"), (0, "D")])
def test_grade_thresholds(score, grade):
    assert grade_for(score) == grade


def test_rank_fills_breakdown_summing_to_score_and_grade(goals, events):
    profiles = [_with_sources("a", "b"),
                profile("p2", "Blake Example", roles=["pm"], topics=["copilot"])]
    matches, _ = asyncio.run(rank(goals, profiles, events=events))
    assert matches
    for match in matches:
        assert match.score_breakdown is not None
        assert match.score_breakdown.total() == match.score
        assert match.grade == grade_for(match.score)
    assert matches[0].score_breakdown.corroboration == 4.0


def test_graph_adjustments_land_in_graph_part(goals, events):
    matches, _ = asyncio.run(rank(goals, [_with_sources("a")], events=events))
    adjusted = apply_graph_adjustments(matches, {"p1": GraphAdjustment(-30.0, "already met")})[0]
    assert adjusted.score_breakdown.graph == -30.0
    assert adjusted.score_breakdown.total() == adjusted.score == round(matches[0].score - 30.0, 2)
    assert adjusted.grade == grade_for(adjusted.score)
