from __future__ import annotations

import pytest

from conferge.core.store import GraphStore
from conferge.integration.memgraph import MemoryGraph


def test_graphstore_round_trip() -> None:
    graph = MemoryGraph()
    store = GraphStore(graph)
    store.merge_node("Person", "p1", {"name": "Ada", "source_mode": "fixture"})
    store.merge_node("Event", "e1", {"title": "Talk"})
    store.merge_edge("Person", "p1", "SPEAKS_AT", "Event", "e1",
                     {"confidence": 1.0, "source": "luma", "source_url": "https://lu.ma/a"})
    store.merge_edge("Person", "p1", "SPEAKS_AT", "Event", "e1",
                     {"source": "luma", "source_url": "https://lu.ma/b"})
    store.merge_node("Person", "p1", {"title": "CTO"})
    assert graph.nodes[("Person", "p1")] == {"name": "Ada", "source_mode": "fixture",
                                             "title": "CTO"}
    assert graph.edges[("Person", "p1", "SPEAKS_AT", "Event", "e1")] == {
        "confidence": 1.0, "source": "luma", "source_url": "https://lu.ma/b",
        "rationale": "SPEAKS_AT recorded from the Luma event page",
        "evidence_ids": ["https://lu.ma/a", "https://lu.ma/b"]}
    assert graph.count_nodes() == {"Event": 1, "Person": 1}
    assert graph.count_edges() == {"SPEAKS_AT": 1}
    assert graph.nodes_missing("source_mode") == ["Event:e1"]


def test_edge_without_endpoints_is_recorded_not_created() -> None:
    graph = MemoryGraph()
    store = GraphStore(graph)
    store.merge_node("Person", "p1")
    store.merge_edge("Person", "p1", "SPEAKS_AT", "Event", "missing",
                     {"source_url": "https://lu.ma/a"})
    assert graph.edges == {}
    assert graph.dangling and "Event:missing" in graph.dangling[0]


def test_non_graphstore_statement_is_refused() -> None:
    graph = MemoryGraph()
    with pytest.raises(ValueError):
        graph.query("CREATE (n:Person {id: 'x'})")
    assert graph.refused == ["CREATE (n:Person {id: 'x'})"]
