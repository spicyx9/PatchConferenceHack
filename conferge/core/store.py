"""Only approved FalkorDB write boundary.

Dynamic Cypher labels/types/property names use a strict allowlist; all values
are parameterized. Feature windows must use GraphStore, never direct MERGE.
"""

from __future__ import annotations

import re
from typing import Any, Protocol

_ALLOWED_NODE_LABELS = frozenset({
    "Conference", "Event", "Person", "Company", "Goal", "Opportunity", "Venue",
    "Topic", "Lodging", "FlightOffer", "Session", "Meeting",
})
_ALLOWED_EDGES = frozenset({
    "PART_OF", "SPEAKS_AT", "HOSTS", "WORKS_AT", "ATTENDS_CONFIRMED",
    "ABOUT", "LOCATED_AT", "HAS_GOAL", "SERVES_GOAL", "NEAR", "INVOLVES",
    "EVIDENCED_BY", "MET", "LED_TO", "CONNECTED_TO", "EXHIBITS_AT",
})
_PROP_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class GraphQuery(Protocol):
    def query(self, q: str, params: dict[str, object] | None = None) -> Any: ...


class GraphStore:
    def __init__(self, graph: GraphQuery) -> None:
        self.graph = graph

    @staticmethod
    def _properties(values: dict[str, Any], alias: str) -> tuple[str, dict[str, Any]]:
        assignments: list[str] = []
        params: dict[str, Any] = {}
        for index, (key, value) in enumerate(sorted(values.items())):
            if not _PROP_RE.fullmatch(key) or key == "id":
                raise ValueError(f"unsupported graph property: {key!r}")
            if isinstance(value, dict) or (isinstance(value, list) and any(
                isinstance(item, (dict, list)) for item in value
            )):
                raise ValueError(f"graph property must be scalar or flat list: {key!r}")
            param_name = f"prop_{index}"
            assignments.append(f"{alias}.{key} = ${param_name}")
            params[param_name] = value
        return (" SET " + ", ".join(assignments) if assignments else ""), params

    def merge_node(
        self, kind: str, node_id: str, properties: dict[str, Any] | None = None
    ) -> Any:
        if kind not in _ALLOWED_NODE_LABELS:
            raise ValueError(f"unsupported graph node: {kind}")
        if not node_id:
            raise ValueError("node_id must not be empty")
        set_clause, prop_params = self._properties(properties or {}, "n")
        cypher = f"MERGE (n:{kind} {{id: $id}}){set_clause} RETURN n.id"
        return self.graph.query(cypher, params={"id": node_id, **prop_params})

    def merge_edge(
        self,
        from_kind: str, from_id: str, relation: str, to_kind: str, to_id: str,
        properties: dict[str, Any] | None = None,
    ) -> Any:
        if from_kind not in _ALLOWED_NODE_LABELS or to_kind not in _ALLOWED_NODE_LABELS:
            raise ValueError("unsupported graph node kind")
        if relation not in _ALLOWED_EDGES:
            raise ValueError(f"unsupported graph relation: {relation}")
        if not from_id or not to_id:
            raise ValueError("edge endpoints must not be empty")
        set_clause, prop_params = self._properties(properties or {}, "r")
        cypher = (
            f"MATCH (a:{from_kind} {{id: $from_id}}), (b:{to_kind} {{id: $to_id}}) "
            f"MERGE (a)-[r:{relation}]->(b){set_clause} RETURN a.id, b.id"
        )
        return self.graph.query(
            cypher, params={"from_id": from_id, "to_id": to_id, **prop_params}
        )


def connect_graph():  # type: ignore[no-untyped-def]
    """Connect only when called; import remains testable without FalkorDB running."""
    from falkordb import FalkorDB

    from conferge.core.settings import env_value, falkordb_address

    host, port = falkordb_address()
    args: dict[str, Any] = {"host": host, "port": port}
    if env_value("FALKORDB_PASSWORD"):
        args["password"] = env_value("FALKORDB_PASSWORD")
    db = FalkorDB(**args)
    return GraphStore(db.select_graph(env_value("FALKORDB_GRAPH", "conferge") or "conferge"))
