"""Pure opportunity utility U(o), from docs/knowledge/10-agents-planning.md.

    U(o) = wg G + wp P + ws S + wn N - wt T - wc C - wr R

Every component is normalized to [0, 1] by the candidate builder, so the
best possible U is the sum of positive weights; the 0-100 score is U divided
by that maximum. The breakdown keeps each term and the facts behind it so a
ranking can always be explained.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

CandidateKind = Literal["person", "event"]


@dataclass(frozen=True)
class Weights:
    goal: float = 0.35          # G goal alignment
    people: float = 0.25        # P value of target people present
    topic: float = 0.15         # S topic relevance
    novelty: float = 0.10       # N company novelty / serendipity
    time: float = 0.07          # T time consumed (duration + travel)
    cost: float = 0.04          # C money cost
    uncertainty: float = 0.04   # R uncertainty (presence, evidence, venue)

    @property
    def max_utility(self) -> float:
        return self.goal + self.people + self.topic + self.novelty


DEFAULT_WEIGHTS = Weights()

COMPONENTS: list[tuple[str, str, int]] = [
    # (attribute on Weights and Candidate, letter, sign)
    ("goal", "G", 1), ("people", "P", 1), ("topic", "S", 1), ("novelty", "N", 1),
    ("time", "T", -1), ("cost", "C", -1), ("uncertainty", "R", -1),
]


@dataclass
class Candidate:
    """Normalized inputs for one opportunity; values must be within [0, 1]."""

    kind: CandidateKind
    id: str
    goal: float = 0.0
    people: float = 0.0
    topic: float = 0.0
    novelty: float = 0.0
    time: float = 0.0
    cost: float = 0.0
    uncertainty: float = 0.0
    bonus: float = 0.0                       # graph path bonus, already weighted
    goal_ids: list[str] = field(default_factory=list)
    facts: list[str] = field(default_factory=list)   # human-readable, source-cited
    path: list[dict[str, Any]] = field(default_factory=list)
    notes: dict[str, str] = field(default_factory=dict)  # per-component reason

    def __post_init__(self) -> None:
        for name, _, _ in COMPONENTS:
            value = getattr(self, name)
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name}={value} outside [0, 1] for {self.id}")


@dataclass(frozen=True)
class ScoreBreakdown:
    score: float                 # 0..100
    utility: float               # raw U
    terms: dict[str, float]      # signed weighted contribution per letter
    explanation: str


def _clip(value: float) -> float:
    return max(0.0, min(1.0, value))


def score_candidate(candidate: Candidate, weights: Weights = DEFAULT_WEIGHTS) -> ScoreBreakdown:
    terms: dict[str, float] = {}
    parts: list[str] = []
    for name, letter, sign in COMPONENTS:
        weight = getattr(weights, name)
        value = getattr(candidate, name)
        contribution = sign * weight * value
        terms[letter] = round(contribution, 4)
        note = candidate.notes.get(letter)
        parts.append(
            f"{'+' if sign > 0 else '-'}{weight:.2f}x{letter}({value:.2f})"
            + (f" [{note}]" if note else "")
        )
    utility = sum(terms.values()) + candidate.bonus
    if candidate.bonus:
        terms["graph_bonus"] = round(candidate.bonus, 4)
        parts.append(f"+graph_bonus({candidate.bonus:.3f})")
    score = round(100.0 * _clip(utility / weights.max_utility), 1)
    explanation = f"score {score} = 100 x U/{weights.max_utility:.2f}; U={utility:.3f} = " + " ".join(parts)
    return ScoreBreakdown(score=score, utility=round(utility, 4), terms=terms,
                          explanation=explanation)
