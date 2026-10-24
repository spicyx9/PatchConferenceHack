"""Optional read-only bridge to the window 08 graph (``conferge.graph``).

The agents work without it. When a ``GraphStore`` (or raw graph) is supplied,
this reader pulls memory (MET/CONTACTED) and goal-to-person paths; every
failure becomes a warning so the caller can report ``status=degraded``.
"""

from __future__ import annotations

from typing import Any

from conferge.agents.networking.recommend import GraphHint
from conferge.core.schemas import Goal


class GraphReader:
    def __init__(self, target: Any) -> None:
        self.target = target
        self.warnings: list[str] = []

    def _module(self) -> Any | None:
        try:
            import conferge.graph as graph
        except Exception as exc:  # noqa: BLE001 - window 08 absent or broken
            self.warnings.append(f"graph module unavailable: {type(exc).__name__}")
            return None
        return graph

    def excluded_people(self, user_id: str) -> set[str]:
        graph = self._module()
        if graph is None:
            return set()
        try:
            rows = graph.people_met_before(self.target, user_id)["rows"]
        except Exception as exc:  # noqa: BLE001 - visible degradation
            self.warnings.append(f"graph memory read failed: {type(exc).__name__}")
            return set()
        return {r["person_id"] for r in rows if r.get("kind") in {"MET", "CONTACTED"}}

    def hints(self, user_id: str, goals: list[Goal]) -> dict[str, GraphHint]:
        graph = self._module()
        if graph is None:
            return {}
        hints: dict[str, GraphHint] = {}
        for goal in goals:
            try:
                result = graph.people_for_goal(self.target, user_id, goal.id, 50)
            except Exception as exc:  # noqa: BLE001
                self.warnings.append(f"graph people_for_goal({goal.id}) failed: {type(exc).__name__}")
                continue
            by_last: dict[str, Any] = {}
            for path in result.get("paths", []):
                nodes = path.get("nodes") or []
                person = next((n["id"] for n in nodes if n.get("label") == "Person"), None)
                if person and person not in by_last:
                    by_last[person] = path
            for row in result.get("rows", []):
                pid = row["person_id"]
                path = by_last.get(pid)
                text = graph.path_to_text(path) if path else ", ".join(row.get("reasons", []))
                hops = row.get("shortest_hops")
                current = hints.get(pid)
                if current is None or (hops is not None and (current.hops is None or hops < current.hops)):
                    hints[pid] = GraphHint(hops=hops, text=text)
        return hints
