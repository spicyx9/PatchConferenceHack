"""Risk 4 of the wiring audit: /reset must also forget the user's MET / SKIPPED memory in FalkorDB."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from fastapi.testclient import TestClient

from conferge.api import providers
from conferge.api.app import create_app
from conferge.api.providers import Providers
from conferge.core.store import GraphStore
from tests.api.test_graph_ranking import GRAPH_ORDER, FakeFalkor, _top


class ForgetfulFalkor(FakeFalkor):
    """FakeFalkor that honours DETACH DELETE of the user's Meeting nodes."""

    def __init__(self, ranked: list[str]) -> None:
        super().__init__(ranked)
        self.deletes: list[tuple[str, dict[str, Any]]] = []

    def query(self, query: str, params: dict[str, Any] | None = None) -> Any:
        if "DELETE" in query:
            self.deletes.append((query, params or {}))
            if query.startswith("MATCH (m:Meeting"):
                deleted, self.met = len(self.met), []
                return SimpleNamespace(nodes_deleted=deleted, relationships_deleted=deleted)
            return SimpleNamespace(nodes_deleted=0, relationships_deleted=0)
        return super().query(query, params)


def _client(monkeypatch, graph) -> TestClient:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(providers, "connect_store", lambda: GraphStore(graph))
    return TestClient(create_app(found=Providers(), graph_probe=True))


def test_reset_forgets_met_in_the_graph_and_restores_the_ranking(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    graph = ForgetfulFalkor(GRAPH_ORDER)
    client = _client(monkeypatch, graph)
    before, _ = _top(client)
    client.post("/api/v1/met", json={"person_id": before[0]})
    assert _top(client)[0] == before[1:]  # excluded by the graph memory

    body = client.post("/api/v1/reset").json()
    assert body["graph_memory_cleared"] == {"nodes_deleted": 1, "relationships_deleted": 1}
    assert all(p["user_id"] == "demo-user" for _, p in graph.deletes)
    assert [q.split(" ")[1] for q, _ in graph.deletes] == ["(m:Meeting", "(c:Change", "(:User"]
    assert not any(w.startswith("graph memory kept") for w in body["warnings"])
    assert _top(client)[0] == before  # the same demo can be replayed
    assert _top(_client(monkeypatch, graph))[0] == before  # and survives a process restart


def test_reset_says_so_when_the_graph_memory_cannot_be_cleared(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    class StubbornFalkor(FakeFalkor):
        def query(self, query: str, params: dict[str, Any] | None = None) -> Any:
            if "DELETE" in query:
                raise RuntimeError("read-only")
            return super().query(query, params)

    graph = StubbornFalkor(GRAPH_ORDER)
    client = _client(monkeypatch, graph)
    client.post("/api/v1/met", json={"person_id": GRAPH_ORDER[0]})
    body = client.post("/api/v1/reset").json()
    assert body["graph_memory_cleared"] is None
    assert any(w.startswith("graph memory kept") for w in body["warnings"])
    assert _top(client)[0] == GRAPH_ORDER[1:]  # honest: still excluded


def test_reset_without_graph_reports_nothing_cleared() -> None:
    client = TestClient(create_app(found=Providers(), graph_probe=False))
    body = client.post("/api/v1/reset").json()
    assert body["graph_memory_cleared"] is None
    assert not any(w.startswith("graph memory kept") for w in body["warnings"])
