"""Pre-demo checks against the running demo API and FalkorDB (used by scripts/predemo.sh).

``python scripts/predemo_check.py falkordb``  -> exit 0 when FalkorDB answers GRAPH.LIST.
``python scripts/predemo_check.py api URL``   -> OK/FAIL table, exit 1 when a line fails.

Expected values come from the committed demo data on a freshly reset graph; override with
PREDEMO_TOP3 (comma separated names), PREDEMO_STAYS_BD, PREDEMO_FLIGHTS_BD, PREDEMO_LINKEDIN_MIN.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

DEFAULT_TOP3 = "Ryan Hecht,Camila Maia,Nick Liffen"
MIN_NODES, MIN_EDGES = 600, 2000
ANTIFOMO_MAX_S = 2.0


def expected() -> dict[str, Any]:
    return {
        "top3": [n.strip() for n in os.environ.get("PREDEMO_TOP3", DEFAULT_TOP3).split(",") if n.strip()],
        "stays_bd": int(os.environ.get("PREDEMO_STAYS_BD", "21")),
        "flights_bd": int(os.environ.get("PREDEMO_FLIGHTS_BD", "34")),
        "linkedin_min": int(os.environ.get("PREDEMO_LINKEDIN_MIN", "12")),
    }


def falkordb_address() -> tuple[str, int]:
    from conferge.core.settings import falkordb_address as resolve

    return resolve()


def falkordb_graphs(timeout: float = 2.0) -> list[str]:
    from falkordb import FalkorDB

    host, port = falkordb_address()
    return list(FalkorDB(host=host, port=port, socket_timeout=timeout,
                         socket_connect_timeout=timeout).list_graphs())


def graph_counts(graph: str = "conferge_demo") -> tuple[int, int]:
    from falkordb import FalkorDB

    host, port = falkordb_address()
    g = FalkorDB(host=host, port=port).select_graph(graph)
    nodes = g.ro_query("MATCH (n) RETURN count(n)").result_set[0][0]
    edges = g.ro_query("MATCH ()-[r]->() RETURN count(r)").result_set[0][0]
    return int(nodes), int(edges)


def evaluate(data: dict[str, Any], exp: dict[str, Any]) -> list[tuple[str, bool, str]]:
    """Pure check of collected facts -> (check, ok, detail) rows."""
    rows: list[tuple[str, bool, str]] = []
    nodes, edges = data["graph"]
    rows.append(("FalkorDB graph", nodes >= MIN_NODES and edges >= MIN_EDGES,
                 f"{nodes} nodes, {edges} edges (min {MIN_NODES} / {MIN_EDGES})"))
    pipeline = data["pipeline"].get("rows", [])

    def bd(source: str, api: str | None = None) -> int:
        return sum(r.get("records") or 0 for r in pipeline
                   if r.get("source") == source and r.get("kind") == "brightdata"
                   and r.get("status") != "failed" and (api is None or r.get("brightdata_api") == api))

    stays, flights = bd("stays"), bd("flights", "unlocker")
    rows.append(("Bright Data stays", stays == exp["stays_bd"], f"{stays} (expected {exp['stays_bd']})"))
    rows.append(("Bright Data flights (Web Unlocker)", flights == exp["flights_bd"],
                 f"{flights} (expected {exp['flights_bd']})"))
    cards = data["people"].get("items", [])
    li = sum(1 for c in cards if c.get("linkedin"))
    rows.append(("LinkedIn cards on /people", li >= exp["linkedin_min"], f"{li} (min {exp['linkedin_min']})"))
    top = [((c.get("person") or {}).get("name") or "") for c in cards[:3]]
    rows.append(("Top 3 people", top == exp["top3"], f"{', '.join(top)} (expected {', '.join(exp['top3'])})"))
    secs = data["antifomo_seconds"]
    rows.append(("/antifomo response time", secs is not None and secs < ANTIFOMO_MAX_S,
                 f"{secs:.2f} s (max {ANTIFOMO_MAX_S:.0f} s)" if secs is not None else "no answer"))
    return rows


def _get(url: str, timeout: float = 30.0) -> Any:
    with urllib.request.urlopen(url, timeout=timeout) as r:  # noqa: S310 - local demo API
        return json.loads(r.read())


def collect(base: str, counts: Callable[[], tuple[int, int]] = graph_counts) -> dict[str, Any]:
    api = base.rstrip("/") + "/api/v1"
    # Same order as the page: plan, people and pipeline load before /antifomo is called.
    _get(api + "/plan")
    people, pipeline = _get(api + "/people?limit=50"), _get(api + "/pipeline")
    started = time.perf_counter()
    try:
        _get(api + "/antifomo")
        antifomo: float | None = time.perf_counter() - started
    except Exception:  # noqa: BLE001 - reported as a FAIL line
        antifomo = None
    return {"graph": counts(), "pipeline": pipeline, "people": people, "antifomo_seconds": antifomo}


def table(rows: list[tuple[str, bool, str]]) -> str:
    width = max(len(name) for name, _, _ in rows)
    return "\n".join(f"{'OK  ' if ok else 'FAIL'}  {name.ljust(width)}  {detail}" for name, ok, detail in rows)


def main(argv: list[str]) -> int:
    if argv[:1] == ["falkordb"]:
        host, port = falkordb_address()
        try:
            graphs = falkordb_graphs()
        except Exception as exc:  # noqa: BLE001
            print(f"FalkorDB does not answer GRAPH.LIST on {host}:{port} ({type(exc).__name__}). "
                  "Start it with `make up`, or set FALKORDB_PORT to its port.")
            return 2
        print(f"FalkorDB answers on {host}:{port} ({len(graphs)} graphs)")
        return 0
    if argv[:1] == ["api"] and len(argv) == 2:
        rows = evaluate(collect(argv[1]), expected())
        print(table(rows))
        return 0 if all(ok for _, ok, _ in rows) else 1
    print(__doc__)
    return 64


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
