"""Serialize FalkorDB Node/Edge/Path results into plain JSON-able dicts.

Duck-typed so tests can pass lightweight fakes: a path exposes ``nodes()`` and
``edges()``; a node exposes ``id``, ``labels``, ``properties``; an edge exposes
``relation``, ``src_node``, ``dest_node``, ``properties``.
"""

from __future__ import annotations

from typing import Any, TypedDict


class PathNode(TypedDict):
    id: str
    label: str
    props: dict[str, Any]


class PathEdge(TypedDict):
    source: str
    target: str
    type: str
    props: dict[str, Any]


class SerializedPath(TypedDict):
    nodes: list[PathNode]
    edges: list[PathEdge]


class GraphResult(TypedDict):
    rows: list[dict[str, Any]]
    paths: list[SerializedPath]


def _node_ref(node: Any) -> Any:
    return node.id if hasattr(node, "id") else node


def serialize_node(node: Any) -> PathNode:
    props = dict(getattr(node, "properties", {}) or {})
    labels = getattr(node, "labels", None) or ["?"]
    return {"id": str(props.pop("id", _node_ref(node))), "label": labels[0], "props": props}


def serialize_path(path: Any) -> SerializedPath:
    raw_nodes = list(path.nodes())
    nodes = [serialize_node(n) for n in raw_nodes]
    by_internal = {_node_ref(raw): ser["id"] for raw, ser in zip(raw_nodes, nodes, strict=True)}
    edges: list[PathEdge] = []
    for edge in path.edges():
        src = by_internal.get(_node_ref(edge.src_node), str(_node_ref(edge.src_node)))
        dst = by_internal.get(_node_ref(edge.dest_node), str(_node_ref(edge.dest_node)))
        edges.append({"source": src, "target": dst, "type": edge.relation,
                      "props": dict(getattr(edge, "properties", {}) or {})})
    return {"nodes": nodes, "edges": edges}


def path_key(path: SerializedPath) -> tuple[str, ...]:
    return tuple(n["id"] for n in path["nodes"]) + tuple(e["type"] for e in path["edges"])
