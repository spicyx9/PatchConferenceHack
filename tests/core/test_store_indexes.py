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
