"""FalkorDB 6.0.x server behaviours we rely on (needs a running FalkorDB).

Run: CONFERGE_FALKORDB_TEST=1 FALKORDB_PORT=6380 uv run pytest tests/graph/test_falkordb_server.py
"""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("CONFERGE_FALKORDB_TEST") != "1",
    reason="set CONFERGE_FALKORDB_TEST=1 with a running FalkorDB to run",
)


@pytest.fixture()
def graph():  # type: ignore[no-untyped-def]
    from falkordb import FalkorDB

    from conferge.core.settings import falkordb_address

    host, port = falkordb_address()
    g = FalkorDB(host=host, port=port).select_graph("conferge_w00_server_test")
    try:
        g.delete()
    except Exception:  # noqa: BLE001 - absent graph
        pass
    g.query("CREATE (:Person {id: 'p1', name: 'A'})-[:WORKS_AT]->(:Company {id: 'c1', name: 'Acme'}),"
            " (:Person {id: 'p2', name: 'B'})")
    yield g
    g.delete()


def test_optional_match_null_group_before_aggregation(graph) -> None:  # type: ignore[no-untyped-def]
    # FalkorDB 6.0 regression reported on null rows reaching an aggregation after OPTIONAL MATCH.
    rows = graph.query(
        "MATCH (p:Person) OPTIONAL MATCH (p)-[:WORKS_AT]->(c:Company) RETURN c.name, count(p)"
    ).result_set
    assert sorted(rows, key=lambda r: str(r[0])) == [["Acme", 1], [None, 1]]
