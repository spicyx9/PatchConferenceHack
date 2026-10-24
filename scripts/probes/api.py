"""make probe-api: exercise every w12 route offline and report live integrations.

Writes probes/api.md. Routes run on the labelled fixture (TestClient, no
network). FalkorDB is probed read-only: the probe never writes to the graph.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from conferge.api import providers  # noqa: E402
from conferge.api.app import create_app  # noqa: E402

GET_ROUTES = [
    "/health", "/api/v1/conference", "/api/v1/plan", "/api/v1/people", "/api/v1/events",
    "/api/v1/sessions", "/api/v1/stays", "/api/v1/flights", "/api/v1/travel",
    "/api/v1/travel/map", "/api/v1/graph", "/api/v1/graph/path?person=per-fx-07",
    "/api/v1/scenarios", "/api/v1/roi", "/api/v1/sources",
]


def main() -> int:
    started = datetime.now(timezone.utc)
    found = providers.discover_providers()
    graph_up = providers.falkordb_reachable()
    live_graph = None
    graph_error = None
    if graph_up:
        store = providers.connect_store()
        if store is None:
            graph_error = "port open but not FalkorDB / query failed (" + "; ".join(providers.LAST_GRAPH_ERROR) + ")"
        else:
            live_graph = providers.read_live_graph(store)
            if live_graph is None:
                graph_error = "FalkorDB reachable but graph empty or unreadable"

    rows = []
    # Offline routes: fixture data, graph probe disabled so results are reproducible.
    client = TestClient(create_app(found=found, graph_probe=False))
    goal = client.post("/api/v1/goal", json={"text": client.get("/api/v1/conference").json()["demo_goal_text"]})
    rows.append(("POST /api/v1/goal", goal.status_code, goal.json().get("data_source"), goal.json().get("status")))
    for path in GET_ROUTES:
        res = client.get(path)
        body = res.json()
        rows.append((f"GET {path}", res.status_code, body.get("data_source", "n/a"), body.get("status")))
    sim = client.post("/api/v1/simulate-change", json={"scenario_id": "sold-out-founders-night"})
    rows.append(("POST /api/v1/simulate-change", sim.status_code, sim.json().get("data_source"), sim.json().get("status")))
    met = client.post("/api/v1/met", json={"person_id": "per-fx-07"})
    rows.append(("POST /api/v1/met", met.status_code, met.json().get("data_source"), met.json().get("status")))

    body = goal.json()
    people = len(body.get("people", []))
    days = [d["day"] for d in body["plan"]["days"] if d["items"]]
    failures = [r for r in rows if r[1] != 200]
    live_claims = [r for r in rows if r[2] == "live"]

    lines = [
        "# Probe: api (window 12)",
        "",
        f"- collected_at: {started.isoformat()}",
        "- routes source: `fixtures/api.json` (**fixture**, fictional records, labelled `[FIXTURE]` / `(fictional)`)",
        f"- routes checked: {len(rows)}, non-200: {len(failures)}, responses claiming live: {len(live_claims)}",
        f"- POST /goal with demo text: {people} people, plan days {days}, "
        f"conflicts {len(body['plan']['conflicts'])}, computed_by `{body['computed_by']}`",
        f"- status: {'ok' if not failures and not live_claims else 'failed'} "
        "(API layer works; data is fixture so every envelope reports status `degraded`)",
        "",
        "## Integrations",
        "",
        f"- FalkorDB ({':'.join(map(str, providers._falkordb_address()))}): "
        + ("reachable" if graph_up else "not reachable")
        + (f", live read returned {len(live_graph['nodes'])} nodes / {len(live_graph['edges'])} edges (read-only)"
           if live_graph else (f", {graph_error}" if graph_error else "")),
        "- Bright Data: not called by the API layer (source windows own collection); no key tonight",
        "",
        "| agent module | available | detail |",
        "|---|---|---|",
        *[f"| {s.name} | {s.available} | {s.detail} |" for s in found.statuses],
        "",
        "## Routes",
        "",
        "| route | http | data_source | status |",
        "|---|---|---|---|",
        *[f"| {r[0]} | {r[1]} | {r[2]} | {r[3]} |" for r in rows],
        "",
    ]
    out = ROOT / "probes" / "api.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    return 1 if failures or live_claims else 0


if __name__ == "__main__":
    raise SystemExit(main())
