"""Rankings computed from FalkorDB traversals (people_for_goal, events_for_goal).

This is the ranking of record when the graph answers: person scores are the
evidence scores of ``people_for_goal`` (root-source grouping, noisy-OR) weighted
by goal priority and summed over goals; people the user already MET or
CONTACTED are excluded by the graph query itself, so recording a meeting through
``record_memory`` changes the next ranking without any Python-side state.
"""

from __future__ import annotations

from typing import Any

from conferge.core.schemas import Goal, Opportunity
from conferge.graph.explain import path_to_text
from conferge.graph.queries import events_for_goal, people_for_goal

COMPUTED_BY = "falkordb"
_PRESENCE = {"attendance": "confirmed", "speaker": "probable", "host": "probable"}


def _person_path(paths: list[dict[str, Any]], person_id: str) -> dict[str, Any] | None:
    return next((p for p in paths if p["nodes"] and p["nodes"][-1]["id"] == person_id), None)


def rank_people(target: Any, user_id: str, goals: list[Goal], limit: int = 50) -> list[Opportunity]:
    totals: dict[str, float] = {}
    rows: dict[str, dict[str, Any]] = {}
    goal_ids: dict[str, list[str]] = {}
    best: dict[str, dict[str, Any]] = {}
    for goal in goals:
        result = people_for_goal(target, user_id, goal.id, limit)
        for row in result["rows"]:
            pid = row["person_id"]
            totals[pid] = totals.get(pid, 0.0) + row["score"]
            goal_ids.setdefault(pid, []).append(goal.id)
            if pid not in rows or row["score"] > rows[pid]["score"]:
                rows[pid] = row
                path = _person_path(result["paths"], pid)
                if path is not None:
                    best[pid] = path
    out = []
    for pid in sorted(totals, key=lambda p: (-totals[p], p))[:limit]:
        row, path = rows[pid], best.get(pid)
        event = next((n for n in (path or {}).get("nodes", []) if n["label"] == "Event"), None)
        presence = next((_PRESENCE[r] for r in ("attendance", "speaker", "host")
                         if r in row["reasons"]), "unknown")
        out.append(Opportunity(
            id=f"opp-graph-{pid}",
            title=f"Meet {row['name'] or pid}" + (f" ({row['title']})" if row.get("title") else ""),
            goal_ids=goal_ids[pid], event_id=event["id"] if event else None, person_ids=[pid],
            score=round(min(100.0, 100.0 * totals[pid]), 1),
            rationale=path_to_text(path) if path else "graph match: " + ", ".join(row["reasons"]),
            where=(event["props"].get("title") if event else None),
            presence=presence,  # a public speaker is announced, not confirmed present
            warnings=["unknown_confidence"] if row.get("unknown_confidence") else [],
        ))
    return out


def event_scores(target: Any, user_id: str, goals: list[Goal],
                 people: list[Opportunity], limit: int = 200) -> dict[str, float]:
    """Event value from the graph: target people present (SPEAKS_AT, HOSTS, ATTENDS_CONFIRMED)
    plus 5 points per goal -> topic <- event path."""
    person_score = {pid: o.score for o in people for pid in o.person_ids}
    scores: dict[str, float] = {}
    for goal in goals:
        for row in events_for_goal(target, user_id, goal.id, limit)["rows"]:
            value = sum(person_score.get(pid, 0.0) for pid in row["target_people"])
            value += 5.0 * row["topic_paths"]
            scores[row["event_id"]] = scores.get(row["event_id"], 0.0) + value
    return {eid: round(min(v, 100.0), 1) for eid, v in scores.items()}
