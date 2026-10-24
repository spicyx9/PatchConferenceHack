"""Graph route against a fake FalkorDB result: modes come from node properties."""

from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient

from conferge.api import providers
from conferge.api.app import create_app
from conferge.api.providers import Providers
from conferge.core.store import GraphStore


class FakeGraph:
    def __init__(self, rows: list[tuple[object, object, object]]) -> None:
        self.rows = rows
        self.queries: list[str] = []

    def query(self, q: str, params: dict[str, object] | None = None) -> SimpleNamespace:
        self.queries.append(q)
        if q.startswith("MATCH (a)-[r]->(b)"):
            return SimpleNamespace(result_set=self.rows)
        if q.startswith("MATCH (p:Person"):
            return SimpleNamespace(result_set=[["per-fx-07"]])
        return SimpleNamespace(result_set=[[1]])


def _node(label: str, **props: object) -> SimpleNamespace:
    return SimpleNamespace(labels=[label], properties=props)


def _rel(relation: str, **props: object) -> SimpleNamespace:
    return SimpleNamespace(relation=relation, properties=props)


def _client(monkeypatch, rows) -> tuple[TestClient, FakeGraph]:  # type: ignore[no-untyped-def]
    graph = FakeGraph(rows)
    monkeypatch.setattr(providers, "connect_store", lambda: GraphStore(graph))
    return TestClient(create_app(found=Providers(), graph_probe=True)), graph


def test_live_graph_is_live_only_when_nodes_say_so(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    rows = [(
        _node("Person", id="p1", name="Real Speaker", source_mode="live"),
        _rel("SPEAKS_AT", source="brightdata", confidence=0.9, observed_at="2026-10-24T10:00:00Z"),
        _node("Event", id="e1", title="Talk", source_mode="live"),
    )]
    client, _ = _client(monkeypatch, rows)
    body = client.get("/api/v1/graph").json()
    assert body["backend"] == "falkordb"
    assert body["data_source"] == "live"
    assert body["edges"][0]["evidence_source"] == "brightdata"
    assert client.get("/health").json()["graph_up"] is True


def test_live_graph_without_mode_is_unknown(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    rows = [(
        _node("Person", id="p1", name="X"), _rel("SPEAKS_AT"), _node("Event", id="e1", title="T"),
    )]
    client, _ = _client(monkeypatch, rows)
    assert client.get("/api/v1/graph").json()["data_source"] == "unknown"


def test_mixed_modes(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    rows = [(
        _node("Person", id="p1", name="X", source_mode="live"), _rel("SPEAKS_AT"),
        _node("Event", id="e1", title="T", source_mode="fixture"),
    )]
    client, _ = _client(monkeypatch, rows)
    assert client.get("/api/v1/graph").json()["data_source"] == "mixed"


def test_empty_graph_falls_back_to_dataset(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    client, _ = _client(monkeypatch, [])
    body = client.get("/api/v1/graph").json()
    assert body["backend"] == "api-fallback" and body["data_source"] == "fixture"


def test_met_persists_through_graphstore_when_person_exists(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    client, graph = _client(monkeypatch, [])
    body = client.post("/api/v1/met", json={"person_id": "per-fx-07", "note": "hi"}).json()
    assert body["persisted"] == "falkordb"
    merges = [q for q in graph.queries if "MERGE" in q]
    assert any(q.startswith("MERGE (n:Meeting") for q in merges)
    assert any("MERGE (a)-[r:INVOLVES]->(b)" in q for q in merges)


def test_graph_path_is_queried_in_falkordb_not_the_capped_sample(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from conferge.graph import queries as graph_queries

    client, _ = _client(monkeypatch, [])
    path = {
        "nodes": [
            {"id": "g-1", "label": "Goal", "props": {"name": "Meet seed investors", "source_mode": "fixture"}},
            {"id": "per-x", "label": "Person", "props": {"name": "Ada", "source_mode": "fixture"}},
        ],
        "edges": [{"source": "g-1", "target": "per-x", "type": "ABOUT",
                   "props": {"source": "fixture:w08", "confidence": 0.9}}],
    }
    monkeypatch.setattr(graph_queries, "path_user_to_person",
                        lambda store, user, person: {"rows": [], "paths": [path]})
    body = client.get("/api/v1/graph/path", params={"person": "per-x"}).json()
    assert body["backend"] == "falkordb"
    assert body["node_ids"] == ["g-1", "per-x"]
    assert body["hops"] == 1
    assert body["explanation"]
    assert body["data_source"] == "fixture"
