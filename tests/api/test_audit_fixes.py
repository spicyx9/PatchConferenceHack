"""Audit fixes (figures shown in the UI must come from the graph, a RunReport or user input)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from conferge.api import app as app_module
from conferge.api import logic, providers
from conferge.api.data import load_fixture
from conferge.core.store import GraphStore


class _MeetingGraph:
    """Answers only the MET Meeting read; any other query fails like a graph without data."""

    def __init__(self, rows: list[list[Any]]) -> None:
        self.rows = rows
        self.queries: list[str] = []

    def query(self, q: str, params: dict[str, Any] | None = None) -> Any:
        self.queries.append(q)
        if "Meeting" in q and "RETURN p.id, m.note, m.at" in q:
            return SimpleNamespace(result_set=self.rows)
        raise RuntimeError("not in this fake graph")


def test_fix3_meetings_are_restored_from_the_graph_at_startup(monkeypatch: pytest.MonkeyPatch) -> None:
    data = load_fixture()
    pid = data.people[0].id
    graph = _MeetingGraph([[pid, "talked about seed", "2026-10-28T18:05:00+00:00"],
                           ["person:not-in-dataset", None, None]])
    monkeypatch.setattr(providers, "connect_store", lambda: GraphStore(graph))
    state = app_module.DemoState(data, providers.Providers(), graph_probe=True)
    assert state.met == {pid: "talked about seed"}
    assert state.met_at[pid].isoformat() == "2026-10-28T18:05:00+00:00"
    assert logic.roi_view(state.data, state.goals, [], state.met)["meetings"] == 1
    assert not any("MERGE" in q or "CREATE" in q for q in graph.queries)  # read only


def test_fix3_without_graph_memory_starts_empty() -> None:
    state = app_module.DemoState(load_fixture(), providers.Providers(), graph_probe=False)
    assert state.met == {} and state.restore_memory() == 0


def test_fix4_spend_names_its_stay_and_carries_price_status() -> None:
    data = load_fixture()
    travel = logic.travel_view(data, {"days": []}, set())
    budget = travel["budget"]
    stay_leg = next(leg for leg in travel["itinerary"] if leg["kind"] == "stay")
    assert budget["lodging_stay"]["id"] == stay_leg["stay_id"]  # same stay as the itinerary shows
    assert budget["lodging_price_status"] == data.stays[0].price_status
    assert len(budget["flights_price_status"]) >= 1
    assert "not chosen by you" in budget["spend_basis"]
    roi = logic.roi_view(data, [], [], {})
    assert roi["spend_price_status"]["lodging"] == budget["lodging_price_status"]
    assert roi["spend_basis"] == budget["spend_basis"]
    if budget["lodging_usd"] is None:  # fixture prices are not collected: nothing is estimated
        assert roi["spend_usd"] is None


def _js_function(name: str) -> str:
    from pathlib import Path

    js = (Path(__file__).resolve().parents[2] / "static" / "app.js").read_text()
    start = js.index(f"function {name}(")
    nxt = js.find("\n  function ", start + 1)
    return js[start:nxt if nxt != -1 else len(js)]


def test_fix5_every_amount_in_the_ui_shows_its_price_status() -> None:
    travel = _js_function("renderTravel")
    flight_branch = travel[travel.index('leg.kind === "flight"'):travel.index("var selected")]
    assert "leg.price_status" in flight_branch
    assert "priceStatusText(b.flights_price_status)" in travel
    assert "priceStatusText(b.lodging_price_status)" in travel
    assert "spend_price_status" in _js_function("renderRoi")
