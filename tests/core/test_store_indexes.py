from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

from conferge.core import store as store_mod
from conferge.core.store import INDEX_STATEMENTS, GraphStore


def test_index_statements_are_ddl_with_range_and_fulltext() -> None:
    assert "CREATE INDEX FOR (n:Person) ON (n.id)" in INDEX_STATEMENTS
    assert "CREATE FULLTEXT INDEX FOR (p:Person) ON (p.name, p.bio)" in INDEX_STATEMENTS
    assert "CREATE FULLTEXT INDEX FOR (e:Event) ON (e.title)" in INDEX_STATEMENTS
    assert not any("db.idx.fulltext.createNodeIndex" in s for s in INDEX_STATEMENTS)


def test_ensure_indexes_is_idempotent_and_cached(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(store_mod, "_INDEXED_GRAPHS", set())
    graph = Mock()
    graph.name = "g-test"
    graph.query.side_effect = lambda q, *a, **k: (_ for _ in ()).throw(
        RuntimeError("Attribute 'id' is already indexed")) if "Person) ON (n.id)" in q else None
    store = GraphStore(graph)
    assert store.ensure_indexes() == []  # "already indexed" is not an error
    assert graph.query.call_count == len(INDEX_STATEMENTS)
    assert store.ensure_indexes() == []  # cached: no second round trip
    assert graph.query.call_count == len(INDEX_STATEMENTS)


def test_index_status_reads_db_indexes() -> None:
    graph = Mock()
    graph.query.return_value = SimpleNamespace(result_set=[
        ["Person", ["id", "name"], {"id": ["RANGE"], "name": ["FULLTEXT"]}, {}, "english", [], "NODE",
         "OPERATIONAL", {}]])
    assert GraphStore(graph).index_status() == [{
        "label": "Person", "properties": ["id", "name"],
        "types": {"id": ["RANGE"], "name": ["FULLTEXT"]}, "status": "OPERATIONAL"}]
    graph.query.assert_called_once_with("CALL db.indexes()")


def test_agent_state_labels_and_edges_are_allowed() -> None:
    calls: list[str] = []

    class Recorder:
        def query(self, q: str, params: dict[str, object] | None = None) -> None:
            calls.append(q)

    store = GraphStore(Recorder())
    store.merge_node("User", "demo-user", {"source": "user"})
    store.merge_node("Change", "change:1", {"written_by": "replanner"})
    for rel, frm, to in (("PLANS", "User", "Event"), ("SKIPS", "User", "Event"), ("AFFECTS", "Change", "Event")):
        store.merge_edge(frm, "a", rel, to, "b", {"written_by": "x"})
    assert sum("MERGE" in q for q in calls) == 5
    assert "CREATE INDEX FOR (n:User) ON (n.id)" in INDEX_STATEMENTS


def test_delete_user_state_is_parameterised_and_counts() -> None:
    graph = Mock()
    graph.query.return_value = SimpleNamespace(nodes_deleted=2, relationships_deleted=3)
    counts = GraphStore(graph).delete_user_state("demo-user")
    assert counts == {"nodes_deleted": 6, "relationships_deleted": 9}
    sent = [c.args[0] for c in graph.query.call_args_list]
    assert sent == ["MATCH (m:Meeting {user_id: $user_id}) DETACH DELETE m",
                    "MATCH (c:Change {user_id: $user_id}) DETACH DELETE c",
                    "MATCH (:User {id: $user_id})-[r:PLANS|SKIPS]->() DELETE r"]
    assert all(c.kwargs["params"] == {"user_id": "demo-user"} for c in graph.query.call_args_list)
