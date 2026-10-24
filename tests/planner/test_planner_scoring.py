"""U(o) scoring: monotonicity, clipping, validation, explanation, determinism."""

from __future__ import annotations

import pytest

from conferge.agents.planner.scoring import (
    COMPONENTS,
    DEFAULT_WEIGHTS,
    Candidate,
    Weights,
    score_candidate,
)

BASE = {"goal": 0.5, "people": 0.5, "topic": 0.5, "novelty": 0.5,
        "time": 0.5, "cost": 0.5, "uncertainty": 0.5}


def _score(**values: float) -> float:
    return score_candidate(Candidate(kind="person", id="x", **{**BASE, **values})).score


@pytest.mark.parametrize("name", ["goal", "people", "topic", "novelty"])
def test_positive_terms_raise_score(name: str) -> None:
    assert _score(**{name: 0.2}) < _score(**{name: 0.5}) < _score(**{name: 0.9})


@pytest.mark.parametrize("name", ["time", "cost", "uncertainty"])
def test_negative_terms_lower_score(name: str) -> None:
    assert _score(**{name: 0.2}) > _score(**{name: 0.5}) > _score(**{name: 0.9})


def test_score_is_clipped_to_0_100() -> None:
    worst = Candidate(kind="event", id="w", time=1, cost=1, uncertainty=1)
    best = Candidate(kind="event", id="b", goal=1, people=1, topic=1, novelty=1, bonus=0.5)
    assert score_candidate(worst).score == 0.0
    assert score_candidate(worst).utility < 0
    assert score_candidate(best).score == 100.0
    perfect = Candidate(kind="event", id="p", goal=1, people=1, topic=1, novelty=1)
    assert score_candidate(perfect).score == 100.0


@pytest.mark.parametrize("name", [n for n, _, _ in COMPONENTS])
@pytest.mark.parametrize("value", [-0.01, 1.01])
def test_candidate_rejects_out_of_range(name: str, value: float) -> None:
    with pytest.raises(ValueError, match=name):
        Candidate(kind="person", id="bad", **{name: value})


def test_explanation_names_every_letter_and_notes() -> None:
    cand = Candidate(kind="person", id="x", **BASE, notes={"C": "price unknown"})
    breakdown = score_candidate(cand)
    for letter in "GPSNTCR":
        assert f"x{letter}(" in breakdown.explanation
    assert "[price unknown]" in breakdown.explanation
    assert set(breakdown.terms) == set("GPSNTCR")
    assert breakdown.terms["T"] < 0 < breakdown.terms["G"]


def test_terms_sum_to_utility_and_score() -> None:
    cand = Candidate(kind="event", id="x", goal=0.8, people=0.3, topic=0.6, novelty=1,
                     time=0.4, cost=0.1, uncertainty=0.2)
    b = score_candidate(cand)
    assert sum(b.terms.values()) == pytest.approx(b.utility, abs=1e-3)
    expected = round(100 * b.utility / DEFAULT_WEIGHTS.max_utility, 1)
    assert b.score == pytest.approx(expected, abs=0.1)


def test_graph_bonus_is_visible() -> None:
    plain = score_candidate(Candidate(kind="person", id="x", **BASE))
    boosted = score_candidate(Candidate(kind="person", id="x", **BASE, bonus=0.03))
    assert boosted.score > plain.score
    assert boosted.terms["graph_bonus"] == pytest.approx(0.03)
    assert "graph_bonus" in boosted.explanation
    assert "graph_bonus" not in plain.terms


def test_scoring_is_deterministic() -> None:
    cand = Candidate(kind="person", id="x", **BASE)
    assert score_candidate(cand) == score_candidate(cand)


def test_custom_weights_change_max_utility() -> None:
    weights = Weights(goal=1.0, people=0.0, topic=0.0, novelty=0.0)
    cand = Candidate(kind="event", id="x", goal=0.5)
    assert score_candidate(cand, weights).score == pytest.approx(50.0)
