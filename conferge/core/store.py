"""Only approved FalkorDB write boundary.

Dynamic Cypher labels/types/property names use a strict allowlist; all values
are parameterized. Feature windows must use GraphStore, never direct MERGE.
"""

from __future__ import annotations

import re
from typing import Any, Protocol

from conferge.core.edge_rationale import annotate

_ALLOWED_NODE_LABELS = frozenset({
    "Conference", "Event", "Person", "Company", "Goal", "Opportunity", "Venue",
    "Topic", "Lodging", "FlightOffer", "Session", "Meeting",
    # Shared agent state (conferge/graph/agent_state.py): the user, and plan changes.
    "User", "Change",
})
_ALLOWED_EDGES = frozenset({
    "PART_OF", "SPEAKS_AT", "HOSTS", "WORKS_AT", "ATTENDS_CONFIRMED",
    "ABOUT", "LOCATED_AT", "HAS_GOAL", "SERVES_GOAL", "NEAR", "INVOLVES",
    "EVIDENCED_BY", "MET", "LED_TO", "CONNECTED_TO", "EXHIBITS_AT",
    # Shared agent state: (User)-[:PLANS|SKIPS]->(Event), (Change)-[:AFFECTS]->(Event).
    "PLANS", "SKIPS", "AFFECTS",
})
_PROP_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
# DDL only (FalkorDB 6.x): range index on id for every allowed label, full-text for search.
# Labels cannot be query parameters, hence the allowlist above.
INDEX_STATEMENTS = tuple(
    f"CREATE INDEX FOR (n:{label}) ON (n.id)" for label in sorted(_ALLOWED_NODE_LABELS)
) + (
    "CREATE FULLTEXT INDEX FOR (p:Person) ON (p.name, p.bio)",
    "CREATE FULLTEXT INDEX FOR (e:Event) ON (e.title)",
)
_INDEXED_GRAPHS: set[str] = set()


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

    def ensure_indexes(self, *, force: bool = False) -> list[str]:
        """Create the indexes once per graph name; an existing index is not an error."""
        key = str(getattr(self.graph, "name", id(self.graph)))
        if key in _INDEXED_GRAPHS and not force:
            return []
        errors = []
        for statement in INDEX_STATEMENTS:
            try:
                self.graph.query(statement)
            except Exception as exc:  # noqa: BLE001 - "already indexed" on a second run
                if "already indexed" not in str(exc):
                    errors.append(f"{statement}: {exc}")
        if not errors:
            _INDEXED_GRAPHS.add(key)
        return errors

    def index_status(self) -> list[dict[str, Any]]:
        """CALL db.indexes(): label, properties, types, status (OPERATIONAL when ready)."""
        rows = self.graph.query("CALL db.indexes()").result_set
        return [{"label": r[0], "properties": list(r[1]), "types": dict(r[2]), "status": r[7]}
                for r in rows]

    def delete_user_state(self, user_id: str) -> dict[str, int]:
        """Forget one user's memory and agent state (an explicit user reset).

        Deletes the user's Meeting nodes (MET / ATTENDED / SKIPPED / CONTACTED, with their
        MET and INVOLVES edges) and Change nodes (with AFFECTS), and the user's PLANS / SKIPS
        edges. Conference data, goals and the User node are kept. Parameterised, labels fixed.
        """
        counts = {"nodes_deleted": 0, "relationships_deleted": 0}
        for cypher in (
            "MATCH (m:Meeting {user_id: $user_id}) DETACH DELETE m",
            "MATCH (c:Change {user_id: $user_id}) DETACH DELETE c",
            "MATCH (:User {id: $user_id})-[r:PLANS|SKIPS]->() DELETE r",
        ):
            result = self.graph.query(cypher, params={"user_id": user_id})
            for key in counts:
                counts[key] += int(getattr(result, key, 0) or 0)
        return counts

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
        # Every edge gets a rule-based rationale and at least one evidence id (refused
        # otherwise); evidence ids accumulate across MERGEs, so corroboration never drops one.
        props = annotate(relation, from_kind, from_id, properties or {})
        ids = props.pop("evidence_ids")
        set_clause, prop_params = self._properties(props, "r")
        set_clause = (set_clause or " SET") + (", " if set_clause else " ") + (
            "r.evidence_ids = CASE WHEN r.evidence_ids IS NULL THEN $evidence_ids "
            "ELSE r.evidence_ids + [x IN $evidence_ids WHERE NOT x IN r.evidence_ids] END")
        cypher = (
            f"MATCH (a:{from_kind} {{id: $from_id}}), (b:{to_kind} {{id: $to_id}}) "
            f"MERGE (a)-[r:{relation}]->(b){set_clause} RETURN a.id, b.id"
        )
        return self.graph.query(
            cypher, params={"from_id": from_id, "to_id": to_id, "evidence_ids": ids,
                            **prop_params}
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
    store = GraphStore(db.select_graph(env_value("FALKORDB_GRAPH", "conferge") or "conferge"))
    store.ensure_indexes()
    return store


def connect_graph_or_none(timeout: float = 0.3) -> GraphStore | None:
    """connect_graph() when FalkorDB answers a Cypher ping within ``timeout``, else None.

    The port check comes first so a stopped server costs ``timeout``, not a client hang.
    """
    import socket

    from conferge.core.settings import falkordb_address

    host, port = falkordb_address()
    try:
        with socket.create_connection((host, port), timeout=timeout):
            pass
        store = connect_graph()
        store.graph.query("RETURN 1")
        return store
    except Exception:  # noqa: BLE001 - absent or non-FalkorDB server (plain Redis rejects GRAPH.QUERY)
        return None
