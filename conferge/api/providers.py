"""Optional integrations discovered at runtime.

Each feature window lands its module independently; the API imports it
dynamically and falls back to ``conferge.api.logic`` when absent or failing.
Failures are recorded as warnings and surface as ``status=degraded``.
"""

from __future__ import annotations

import importlib
import inspect
import socket
from dataclasses import dataclass, field
from typing import Any

from conferge.core.schemas import AgentContext, AgentResult

# module path -> attribute names tried in order (function or class with .run)
AGENT_MODULES: dict[str, tuple[str, ...]] = {
    "planner": ("conferge.agents.planner",),
    "networking": ("conferge.agents.networking",),
    "antifomo": ("conferge.agents.antifomo",),
    "replanner": ("conferge.agents.replanner",),
}
_AGENT_ATTRS = ("run", "agent", "Agent", "PlannerAgent", "NetworkingAgent", "AntiFomoAgent", "ReplannerAgent")


@dataclass
class ProviderStatus:
    name: str
    available: bool
    detail: str


@dataclass
class Providers:
    agents: dict[str, Any] = field(default_factory=dict)
    statuses: list[ProviderStatus] = field(default_factory=list)


def _resolve_agent(module: Any) -> Any | None:
    for attr in _AGENT_ATTRS:
        obj = getattr(module, attr, None)
        if obj is None:
            continue
        if inspect.isclass(obj):
            try:
                obj = obj()
            except Exception:  # noqa: BLE001 - constructor needs args we cannot guess
                continue
        if callable(getattr(obj, "run", None)):
            return obj
        if inspect.iscoroutinefunction(obj) or callable(obj):
            return obj
    return None


def discover_providers() -> Providers:
    providers = Providers()
    for name, modules in AGENT_MODULES.items():
        loaded = None
        detail = "not merged yet"
        for path in modules:
            try:
                module = importlib.import_module(path)
            except ImportError:
                continue
            except Exception as exc:  # noqa: BLE001 - a broken module must not break the API
                detail = f"import error: {type(exc).__name__}"
                continue
            loaded = _resolve_agent(module)
            detail = path if loaded else f"{path} has no run()"
            if loaded:
                break
        if loaded is not None:
            providers.agents[name] = loaded
        providers.statuses.append(ProviderStatus(name, loaded is not None, detail))
    return providers


async def run_agent(agent: Any, ctx: AgentContext) -> AgentResult:
    runner = agent.run if callable(getattr(agent, "run", None)) else agent
    result = runner(ctx)
    if inspect.isawaitable(result):
        result = await result
    if isinstance(result, AgentResult):
        return result
    return AgentResult.model_validate(result)


# FalkorDB

def _falkordb_address() -> tuple[str, int]:
    from conferge.core.settings import falkordb_address

    return falkordb_address()


def browser_url(cypher: str) -> str:
    """FalkorDB Browser link with the graph and query pre-filled (Browser share parameters)."""
    from urllib.parse import urlencode

    from conferge.core.settings import env_value

    base = (env_value("FALKORDB_BROWSER_URL", "http://localhost:3000") or "").rstrip("/")
    graph = env_value("FALKORDB_GRAPH", "conferge") or "conferge"
    return f"{base}/graph?" + urlencode({"graph": graph, "query": cypher, "view": "Graph"})


def falkordb_reachable(timeout: float = 0.3) -> bool:
    host, port = _falkordb_address()
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


LAST_GRAPH_ERROR: list[str] = []


def connect_store() -> Any | None:
    """GraphStore when FalkorDB answers a Cypher query, else None. Never raises.

    An open port is not enough: a plain Redis on 6379 rejects GRAPH.QUERY.
    """
    LAST_GRAPH_ERROR.clear()
    if not falkordb_reachable():
        LAST_GRAPH_ERROR.append("port closed")
        return None
    try:
        from conferge.core.store import connect_graph

        store = connect_graph()
        store.graph.query("RETURN 1")
        return store
    except Exception as exc:  # noqa: BLE001 - graph down means fixture graph, visibly
        LAST_GRAPH_ERROR.append(f"{type(exc).__name__}: {str(exc)[:80]}")
        return None


def _entity(obj: Any) -> dict[str, Any]:
    props = dict(getattr(obj, "properties", {}) or {})
    labels = getattr(obj, "labels", None)
    rel = getattr(obj, "relation", None)
    out = {"properties": props}
    if labels is not None:
        out["labels"] = list(labels)
    if rel is not None:
        out["relation"] = rel
    return out


def read_live_graph(store: Any, limit: int = 400) -> dict[str, Any] | None:
    """Read-only query of the shared graph; writes still go through GraphStore."""
    try:
        result = store.graph.query(
            "MATCH (a)-[r]->(b) RETURN a, r, b LIMIT $limit", params={"limit": limit}
        )
    except Exception:  # noqa: BLE001
        return None
    nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, Any]] = []
    for row in getattr(result, "result_set", []) or []:
        a, r, b = (_entity(x) for x in row)
        ids = []
        for ent in (a, b):
            props = ent["properties"]
            nid = str(props.get("id", ""))
            if not nid:
                continue
            ids.append(nid)
            nodes.setdefault(nid, {
                "id": nid,
                "type": (ent.get("labels") or ["Node"])[0],
                "label": str(props.get("name") or props.get("title") or nid),
                "source_mode": props.get("source_mode") or "unknown",
            })
        if len(ids) == 2:
            rp = r["properties"]
            edges.append({
                "id": f"{ids[0]}|{r.get('relation')}|{ids[1]}",
                "source": ids[0], "target": ids[1], "type": r.get("relation"),
                "evidence_source": rp.get("source"), "confidence": rp.get("confidence"),
                "observed_at": rp.get("observed_at"),
            })
    if not nodes:
        return None
    return {"nodes": list(nodes.values())[:limit], "edges": edges}
