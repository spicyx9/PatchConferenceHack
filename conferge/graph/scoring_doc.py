"""How the people score is computed, written from the constants the code uses (not copied by hand)."""

from __future__ import annotations

from typing import Any

from conferge.graph import queries, ranking
from conferge.people.models import GRADE_THRESHOLDS, ScoreBreakdown


def how_it_works() -> dict[str, Any]:
    weights = dict(queries.PATH_WEIGHTS)
    parts = dict(queries.PATH_PART)
    presence = dict(ranking._PRESENCE)
    lines = [
        "People score (graph ranking, conferge/graph/queries.py people_for_goal and ranking.rank_people):",
        "1. For each goal, every graph path from the goal to a person gets "
        "path_score = PATH_WEIGHTS[kind] x path_confidence.",
        "   PATH_WEIGHTS: " + ", ".join(f"{k} {v}" for k, v in weights.items()) + ".",
        f"   path_confidence = the weakest edge confidence on the path; an edge without confidence "
        f"counts as {queries.UNKNOWN_CONFIDENCE} and flags the path '{queries.UNKNOWN_CONFIDENCE_FLAG}'.",
        "   A role match (person role in the goal's target roles) adds a path of kind 'role' "
        f"with weight {weights.get('role')} and no confidence factor.",
        "2. Corroboration: paths are grouped by root source (the provenance of the edge reaching the "
        "person); the best path per source is kept, then sources combine by noisy-OR: "
        "1 - prod(1 - s). Several paths from one page count once.",
        "3. The goal's priority multiplies that value; the person score is "
        "min(100, 100 x sum over goals).",
        "4. Breakdown: the strongest source counts as "
        + ", ".join(f"{k} -> {v}" for k, v in parts.items())
        + "; every further independent source adds its marginal gain to 'corroboration'. "
        "Breakdown fields: " + ", ".join(ScoreBreakdown.model_fields) + "; in the graph ranking "
        "'identity' and 'graph' stay 0 (no identity bonus).",
        "5. Presence label (not a bonus): " + ", ".join(f"{k} -> {v}" for k, v in presence.items())
        + "; otherwise 'unknown'. A public speaker is announced, not confirmed present.",
        "6. Grade: " + ", ".join(f"{g} >= {floor}" for g, floor in GRADE_THRESHOLDS) + ", otherwise D.",
        "Every recommendation carries its evidence path or an explicit fallback rationale: a person "
        "matched on role alone, without a complete event path, stays ranked with that fallback reason.",
        "These weights are hand-set and uncalibrated: they order candidates, they are not probabilities.",
    ]
    return {"path_weights": weights, "unknown_confidence": queries.UNKNOWN_CONFIDENCE,
            "path_parts": parts, "presence_labels": presence, "cap": 100,
            "grade_thresholds": [list(t) for t in GRADE_THRESHOLDS], "calibrated": False,
            "text": "\n".join(lines)}
