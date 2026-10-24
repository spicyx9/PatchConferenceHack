"""Pre-demo checks against the running demo API and FalkorDB (used by scripts/predemo.sh).

``python scripts/predemo_check.py falkordb``  -> exit 0 when FalkorDB answers GRAPH.LIST.
``python scripts/predemo_check.py api URL``   -> OK/FAIL table, exit 1 when a line fails.

Expected values come from the committed demo data on a freshly reset graph; override with
PREDEMO_TOP3 (comma separated names), PREDEMO_STAYS_BD, PREDEMO_FLIGHTS_BD, PREDEMO_LINKEDIN_MIN.

The agenda size, the sold-out event of the simulation and its replacement are compared with
the values measured in STATUS.md (rows "Agenda items", "Sold-out event", "Replacement event");
a missing STATUS.md value is a FAIL, never a default.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

DEFAULT_TOP3 = "Ryan Hecht,Camila Maia,Nick Liffen"
STATUS_MD = Path(__file__).resolve().parents[1] / "STATUS.md"
_STATUS_ROWS = {"agenda": r"^\| Agenda items[^|]*\| (\d+) \|",
                "sold_out": r"^\| Sold-out event[^|]*\| ([^|]+?) \|",
                "replacement": r"^\| Replacement event[^|]*\| ([^|]+?) \|"}
MIN_NODES, MIN_EDGES = 600, 2000
ANTIFOMO_MAX_S = 2.0


def expected() -> dict[str, Any]:
    return {
        "top3": [n.strip() for n in os.environ.get("PREDEMO_TOP3", DEFAULT_TOP3).split(",") if n.strip()],
        "stays_bd": int(os.environ.get("PREDEMO_STAYS_BD", "21")),
        "flights_bd": int(os.environ.get("PREDEMO_FLIGHTS_BD", "34")),
        "linkedin_min": int(os.environ.get("PREDEMO_LINKEDIN_MIN", "12")),
    }


def status_values(path: Path = STATUS_MD) -> dict[str, str | None]:
    """Agenda size, sold-out event and replacement as written in STATUS.md (None if absent)."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        text = ""
    found = {k: re.search(rx, text, re.M) for k, rx in _STATUS_ROWS.items()}
    return {k: (m.group(1).strip() if m else None) for k, m in found.items()}


def stage_rows(agenda: int | None, sold_out: str | None, replacement: str | None,
               status: dict[str, str | None]) -> list[tuple[str, bool, str]]:
    """Pure: the three stage values against STATUS.md."""
    def row(name: str, got: Any, want: str | None) -> tuple[str, bool, str]:
        if want is None:
            return name, False, f"{got} (STATUS.md has no measured value)"
        return name, got is not None and str(got) == want, f"{got} (STATUS.md: {want})"

    return [row("Agenda items", agenda, status["agenda"]),
            row("Sold-out event (simulation)", sold_out, status["sold_out"]),
            row("Replacement event", replacement, status["replacement"])]


def _post(url: str, body: dict[str, Any], timeout: float = 30.0) -> Any:
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 - local demo API
        return json.loads(r.read())


def scenario(base: str) -> tuple[str | None, str | None]:
    """Sold-out event and its replacement from the labelled simulation; session reset after."""
    api = base.rstrip("/") + "/api/v1"
    items = _get(api + "/scenarios").get("items") or []
    if not items:
        return None, None
    try:
        res = _post(api + "/simulate-change", {"scenario_id": items[0]["id"]})
    finally:
        _post(api + "/reset", {})
    diff = res.get("diff") or {}
    titles = {e["id"]: e["title"] for e in _get(api + "/events").get("items") or []}
    sold = [titles.get(c if isinstance(c, str) else c.get("id"), str(c))
            for c in res.get("changed_events") or []]
    added = [a["title"] for a in diff.get("added") or []]
    return (sold[0] if sold else None), (added[0] if added else None)


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


def graph_breakdown(graph: str = "conferge_demo") -> dict[str, dict[str, int]]:
    """Node count per label and edge count per type."""
    from falkordb import FalkorDB

    host, port = falkordb_address()
    g = FalkorDB(host=host, port=port).select_graph(graph)
    return {"labels": {str(r[0]): int(r[1]) for r in g.ro_query("MATCH (n) RETURN labels(n)[0], count(n)").result_set},
            "edges": {str(r[0]): int(r[1]) for r in g.ro_query("MATCH ()-[r]->() RETURN type(r), count(r)").result_set}}


def graph_counts_row(before: dict[str, dict[str, int]], after: dict[str, dict[str, int]]) -> tuple[str, bool, str]:
    """Pure, information only (no threshold): counts when loaded, then after the page wrote its plan."""
    def total(b: dict[str, dict[str, int]], key: str) -> int:
        return sum(b.get(key, {}).values())

    delta = [f"+{after[k].get(n, 0) - before[k].get(n, 0)} {n}"
             for k in ("labels", "edges") for n in sorted(set(after.get(k, {})) | set(before.get(k, {})))
             if after[k].get(n, 0) != before[k].get(n, 0)]
    return ("Graph counts (info)", True,
            f"loaded {total(before, 'labels')} nodes / {total(before, 'edges')} edges; "
            f"after plan {total(after, 'labels')} / {total(after, 'edges')}"
            + (f" ({', '.join(delta)})" if delta else ""))


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


def collect(base: str, counts: Callable[[], tuple[int, int]] = graph_counts,
            breakdown: Callable[[], dict[str, dict[str, int]]] | None = None) -> dict[str, Any]:
    api = base.rstrip("/") + "/api/v1"
    loaded = breakdown() if breakdown else None  # before the page's first calls write the plan
    # Same order as the page: plan, people and pipeline load before /antifomo is called.
    plan = _get(api + "/plan")
    agenda = sum(len(d.get("items") or []) for d in (plan.get("plan") or {}).get("days") or [])
    people, pipeline = _get(api + "/people?limit=50"), _get(api + "/pipeline")
    started = time.perf_counter()
    try:
        _get(api + "/antifomo")
        antifomo: float | None = time.perf_counter() - started
    except Exception:  # noqa: BLE001 - reported as a FAIL line
        antifomo = None
    return {"graph": counts(), "pipeline": pipeline, "people": people, "antifomo_seconds": antifomo,
            "agenda_items": agenda, "graph_loaded": loaded}


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
        data = collect(argv[1], breakdown=graph_breakdown)
        rows = evaluate(data, expected())
        rows.append(graph_counts_row(data["graph_loaded"], graph_breakdown()))
        sold, replacement = scenario(argv[1])
        rows += stage_rows(data.get("agenda_items"), sold, replacement, status_values())
        print(table(rows))
        return 0 if all(ok for _, ok, _ in rows) else 1
    print(__doc__)
    return 64


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
