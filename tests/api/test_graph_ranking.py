"""The ranking comes from FalkorDB traversals; without the graph the API says it is degraded."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from falkordb import Edge, Node, Path
from fastapi.testclient import TestClient

from conferge.api import providers
from conferge.api.app import create_app
from conferge.api.providers import Providers
from conferge.core.store import GraphStore
from conferge.graph import queries as q

_ids = iter(range(1, 10_000))


def _node(label: str, node_id: str, **props: Any) -> Node:
    return Node(node_id=next(_ids), labels=label, properties={"id": node_id, **props})


def _speaker_path(goal_id: str, person_id: str, event_id: str, confidence: float) -> Path:
    goal, topic = _node("Goal", goal_id), _node("Topic", "topic:x", name="X")
    event, person = _node("Event", event_id, title=event_id), _node("Person", person_id, name=person_id)
    edges = [Edge(goal.id, "ABOUT", topic.id, properties={"source": "user", "confidence": 1.0}),
             Edge(event.id, "ABOUT", topic.id, properties={"source": "s", "source_url": "u", "confidence": 1.0}),
             Edge(person.id, "SPEAKS_AT", event.id,
                  properties={"source": "s", "source_url": "u", "confidence": confidence})]
    return Path([goal, topic, event, person], edges)


class FakeFalkor:
    """Answers the named read queries; MET memory is held like FalkorDB would hold it."""

    def __init__(self, ranked: list[str]) -> None:
        self.ranked = ranked
        self.met: list[str] = []
        self.name = "fake"

    def ro_query(self, query: str, params: dict[str, Any] | None = None) -> Any:
        params = params or {}
        rows: list[list[Any]] = []
        if query is q.Q_GOAL:
            rows = [[1.0, "goal"]]
        elif query is q.Q_PEOPLE_MET_BEFORE:
            rows = [[pid, pid, "MET", "2026-10-28T09:00:00+00:00", None] for pid in self.met]
        elif query is q.Q_PEOPLE_VIA_SPEAKER:
            rows = [[pid, _speaker_path(params["goal_id"], pid, f"evt-{pid}", 1.0 - 0.1 * i)]
                    for i, pid in enumerate(self.ranked)]
        elif query is q.Q_PERSON_NAMES:
            rows = [[pid, pid, None, []] for pid in params["ids"]]
        return SimpleNamespace(result_set=rows)

    def query(self, query: str, params: dict[str, Any] | None = None) -> Any:
        if "[r:MET]" in query and params:
            self.met.append(params["to_id"])
        if query.startswith("MATCH (m:Meeting {user_id: $user_id}) DETACH DELETE m"):
            deleted, self.met = len(self.met), []
            return SimpleNamespace(result_set=[], nodes_deleted=deleted, relationships_deleted=deleted)
        return SimpleNamespace(result_set=[[1]])


GRAPH_ORDER = ["per-fx-12", "per-fx-04", "per-fx-10"]  # the Python fallback ranks these last


def _client(monkeypatch, graph: FakeFalkor | None) -> TestClient:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(providers, "connect_store", lambda: GraphStore(graph) if graph else None)
    return TestClient(create_app(found=Providers(), graph_probe=True))


def _top(client: TestClient) -> tuple[list[str], dict[str, Any]]:
    body = client.get("/api/v1/people?limit=3").json()
    return [c["person"]["id"] for c in body["items"]], body


def test_ranking_is_read_from_the_graph(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    ids, body = _top(_client(monkeypatch, FakeFalkor(GRAPH_ORDER)))
    assert ids == GRAPH_ORDER
    assert body["data_source"] == "fixture"  # data mode, not degraded
    plan = _client(monkeypatch, FakeFalkor(GRAPH_ORDER)).get("/api/v1/plan").json()
    assert plan["computed_by"] == "falkordb" and plan["ranking_mode"] == "graph"


def test_graph_is_not_decoration(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    with_graph, _ = _top(_client(monkeypatch, FakeFalkor(GRAPH_ORDER)))
    without, body = _top(_client(monkeypatch, None))
    assert body["data_source"] == "degraded_no_graph" and body["status"] == "degraded"
    assert any("degraded_no_graph" in w for w in body["warnings"])
    assert without != with_graph


def test_met_is_reread_from_the_graph(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    graph = FakeFalkor(GRAPH_ORDER)
    client = _client(monkeypatch, graph)
    res = client.post("/api/v1/met", json={"person_id": "per-fx-12"}).json()
    assert res["persisted"] == "falkordb" and graph.met == ["per-fx-12"]
    after, _ = _top(client)
    assert after == ["per-fx-04", "per-fx-10"]  # excluded by the graph memory query
    restarted, _ = _top(_client(monkeypatch, graph))  # fresh app state, same graph
    assert restarted == after


def test_reset_clears_graph_memory(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    graph = FakeFalkor(GRAPH_ORDER)
    client = _client(monkeypatch, graph)
    client.post("/api/v1/met", json={"person_id": "per-fx-12"})
    assert _top(client)[0][0] != "per-fx-12"
    body = client.post("/api/v1/reset").json()
    assert body["graph_memory_cleared"]["nodes_deleted"] == 1 and graph.met == []
    assert _top(client)[0] == GRAPH_ORDER  # back: the graph no longer remembers the meeting
