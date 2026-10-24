from unittest.mock import Mock

import pytest

from conferge.core.store import GraphStore


def test_graphstore_parameterized_and_typed():
    graph = Mock()
    store = GraphStore(graph)
    store.merge_node("Event", "e1", {"name": "demo' RETURN n", "source": "luma"})
    query = graph.query.call_args.args[0]
    params = graph.query.call_args.kwargs["params"]
    assert "MERGE (n:Event {id: $id})" in query
    assert "demo' RETURN n" not in query
    assert params["id"] == "e1"
    assert "demo' RETURN n" in params.values()


def test_graphstore_injection_blocked():
    graph = Mock()
    store = GraphStore(graph)
    with pytest.raises(ValueError):
        store.merge_node("Event) DELETE", "e1")
    with pytest.raises(ValueError):
        store.merge_node("Person", "p1", {"name) DELETE n": "evil"})
    with pytest.raises(ValueError):
        store.merge_edge("Person", "p1", "HACK]->", "Event", "e1")
    graph.query.assert_not_called()


def test_edge_uses_parameterized_merge():
    graph = Mock()
    store = GraphStore(graph)
    store.merge_edge("Person", "p1", "SPEAKS_AT", "Event", "e1",
                     {"confidence": 0.85})
    assert "MERGE (a)-[r:SPEAKS_AT]->(b)" in graph.query.call_args.args[0]
    assert graph.query.call_args.kwargs["params"]["prop_0"] == 0.85
