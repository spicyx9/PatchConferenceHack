"""In-memory stand-in for a FalkorDB graph, for offline E2E runs.

It understands exactly the two Cypher shapes ``conferge.core.store.GraphStore``
emits (node MERGE, edge MATCH+MERGE). Any other statement is refused and
recorded, which is how the harness detects writes that bypass GraphStore.

It reproduces one FalkorDB behaviour that matters for integration: an edge
whose endpoints were never merged matches nothing and is silently not created.
Here such edges are recorded in ``dangling`` so the report can show them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

_NODE_RE = re.compile(
    r"^MERGE \(n:(?P<kind>\w+) \{id: \$id\}\)(?P<set> SET .*?)? RETURN n\.id$"
)
_EDGE_RE = re.compile(
    r"^MATCH \(a:(?P<fk>\w+) \{id: \$from_id\}\), \(b:(?P<tk>\w+) \{id: \$to_id\}\) "
    r"MERGE \(a\)-\[r:(?P<rel>\w+)\]->\(b\)(?P<set> SET .*?)? RETURN a\.id, b\.id$"
)
_ASSIGN_RE = re.compile(r"(?:n|r)\.(\w+) = \$(\w+)")


@dataclass
class QueryResult:
    result_set: list[list[Any]] = field(default_factory=list)


@dataclass
class MemoryGraph:
    nodes: dict[tuple[str, str], dict[str, Any]] = field(default_factory=dict)
    edges: dict[tuple[str, str, str, str, str], dict[str, Any]] = field(default_factory=dict)
    dangling: list[str] = field(default_factory=list)
    refused: list[str] = field(default_factory=list)
    queries: int = 0

    @staticmethod
    def _props(set_clause: str | None, params: dict[str, Any]) -> dict[str, Any]:
        if not set_clause:
            return {}
        return {key: params[name] for key, name in _ASSIGN_RE.findall(set_clause)}

    def query(self, q: str, params: dict[str, object] | None = None) -> QueryResult:
        self.queries += 1
        values: dict[str, Any] = dict(params or {})
        if match := _NODE_RE.fullmatch(q):
            key = (match["kind"], str(values["id"]))
            self.nodes.setdefault(key, {}).update(self._props(match["set"], values))
            return QueryResult([[key[1]]])
        if match := _EDGE_RE.fullmatch(q):
            src = (match["fk"], str(values["from_id"]))
            dst = (match["tk"], str(values["to_id"]))
            missing = [f"{k}:{i}" for k, i in (src, dst) if (k, i) not in self.nodes]
            if missing:
                self.dangling.append(
                    f"{src[0]}:{src[1]} -[{match['rel']}]-> {dst[0]}:{dst[1]} "
                    f"(missing {', '.join(missing)})"
                )
                return QueryResult([])
            key = (src[0], src[1], match["rel"], dst[0], dst[1])
            self.edges.setdefault(key, {}).update(self._props(match["set"], values))
            return QueryResult([[src[1], dst[1]]])
        self.refused.append(q[:120])
        raise ValueError("MemoryGraph accepts only GraphStore MERGE statements")

    def count_nodes(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for kind, _ in self.nodes:
            out[kind] = out.get(kind, 0) + 1
        return dict(sorted(out.items()))

    def count_edges(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for _, _, rel, _, _ in self.edges:
            out[rel] = out.get(rel, 0) + 1
        return dict(sorted(out.items()))

    def nodes_missing(self, prop: str) -> list[str]:
        return [f"{k}:{i}" for (k, i), props in self.nodes.items() if props.get(prop) is None]
