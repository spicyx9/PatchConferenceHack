"""Visible degradation: empty context, default goals, graph absent/failing, data mode."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from planner_helpers import load_fixture, make_ctx, plan_of, ranking, raw_context, run_planner

import conferge.graph as graph_module
from conferge.core.schemas import AgentContext

EXPECTED = load_fixture()["expected"]


class EmptyGraph:
    """Raw graph whose every read returns no rows."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def query(self, q: str, params: dict[str, object] | None = None) -> Any:
        self.calls.append(q)
        return SimpleNamespace(result_set=[])


class BrokenGraph:
    def query(self, q: str, params: dict[str, object] | None = None) -> Any:
        raise ConnectionError("falkordb down")


async def test_empty_context_is_degraded_not_crashing() -> None:
    raw = raw_context()
    raw["people"], raw["events"] = [], []
    res = await run_planner(AgentContext.model_validate(raw))
    assert res.status == "degraded"
    assert res.opportunities == []
    assert any("empty context" in e for e in res.errors)
    assert plan_of(res)["days"] == []
    assert plan_of(res)["rejected"] == []
    assert res.source_mode == "fixture"  # falls back to declared data_mode


async def test_no_goals_and_no_goal_text_uses_defaults_and_degrades() -> None:
    raw = raw_context()
    raw["constraints"] = {}
    res = await run_planner(AgentContext.model_validate(raw))
    assert res.status == "degraded"
    assert any("default goals used" in e for e in res.explanations)
    assert any("goal-seed-investors" in e for e in res.explanations)
    assert res.opportunities  # defaults still produce a ranking


async def test_parsed_goals_are_not_degraded() -> None:
    res = await run_planner(make_ctx())
    assert res.status == "ok"
    assert any("parsed goals used" in e for e in res.explanations)


async def test_graph_none_is_explained() -> None:
    res = await run_planner(make_ctx(), graph=None)
    assert any("graph not connected" in e for e in res.explanations)
    assert res.status == "ok"


async def test_connected_empty_graph_is_ok() -> None:
    fake = EmptyGraph()
    res = await run_planner(make_ctx(), graph=fake)
    assert res.status == "ok"
    assert res.errors == []
    assert any("graph connected" in e for e in res.explanations)
    assert fake.calls, "graph was not queried"
    assert all("MERGE" not in q and "CREATE" not in q for q in fake.calls)
    assert ranking(res) == EXPECTED["people_ranking"]


async def test_failing_graph_degrades_but_still_ranks() -> None:
    res = await run_planner(make_ctx(), graph=BrokenGraph())
    assert res.status == "degraded"
    assert any("graph memory read failed: ConnectionError" in e for e in res.errors)
    assert any("people_for_goal" in e for e in res.errors)
    assert ranking(res) == EXPECTED["people_ranking"]
    assert plan_of(res)["days"]


async def test_graph_module_missing_function_degrades(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delattr(graph_module, "people_met_before")
    res = await run_planner(make_ctx(), graph=EmptyGraph())
    assert res.status == "degraded"
    assert any("graph memory read failed: AttributeError" in e for e in res.errors)


async def test_graph_memory_excludes_met_person(monkeypatch: pytest.MonkeyPatch) -> None:
    def met_before(target: Any, user_id: str) -> dict[str, Any]:
        assert user_id == make_ctx().user_id
        return {"rows": [{"person_id": "fx-p-inv-bo", "kind": "MET"},
                         {"person_id": "fx-p-inv-di", "kind": "SKIPPED"}], "paths": []}

    monkeypatch.setattr(graph_module, "people_met_before", met_before)
    res = await run_planner(make_ctx(), graph=EmptyGraph())
    assert "fx-p-inv-bo" not in ranking(res)
    assert "fx-p-inv-di" in ranking(res)  # only MET/CONTACTED exclude


async def test_graph_hint_adds_bonus_and_fact(monkeypatch: pytest.MonkeyPatch) -> None:
    baseline = await run_planner(make_ctx())
    base_eve = next(o for o in baseline.opportunities if o.person_ids == ["fx-p-pm-eve"])

    def for_goal(target: Any, user_id: str, goal_id: str, limit: int) -> dict[str, Any]:
        if goal_id != "goal-pm":
            return {"rows": [], "paths": []}
        return {"rows": [{"person_id": "fx-p-pm-eve", "shortest_hops": 2,
                          "reasons": ["speaks on copilot"]}], "paths": []}

    monkeypatch.setattr(graph_module, "people_for_goal", for_goal)
    res = await run_planner(make_ctx(), graph=EmptyGraph())
    eve = next(o for o in res.opportunities if o.person_ids == ["fx-p-pm-eve"])
    assert eve.score > base_eve.score
    assert "graph path (2 hops): speaks on copilot" in eve.rationale
    assert "graph_bonus" in eve.rationale
    assert any("1 people have a goal path" in e for e in res.explanations)


async def test_evidence_mode_wins_over_declared_live() -> None:
    raw = raw_context()
    raw["data_mode"] = "live"
    res = await run_planner(AgentContext.model_validate(raw))
    assert res.source_mode == "fixture"
    assert any("context declared live" in e for e in res.explanations)
    assert any("not live claims" in e for e in res.explanations)


async def test_mixed_evidence_reports_mixed() -> None:
    raw = raw_context()
    raw["people"][0]["evidence"][0]["source_mode"] = "live"
    res = await run_planner(AgentContext.model_validate(raw))
    assert res.source_mode == "mixed"


async def test_ignored_blocked_slot_degrades_status() -> None:
    from planner_helpers import make_ctx as _make_ctx
    from planner_helpers import run_planner as _run

    res = await _run(_make_ctx(blocked=[{"start": "2026-10-28T10:00:00", "end": "x"}]))
    assert res.status == "degraded"
    assert any("ignored blocked slot" in e for e in res.errors)
