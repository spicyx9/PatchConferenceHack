"""Probe w08: seed the fixture graph into FalkorDB, run named traversals, write probes/graph.md.

Run: ``make probe-graph`` (FALKORDB_HOST/FALKORDB_PORT/FALKORDB_GRAPH from env).
The database round-trip is live; the graph *data* is the labelled w08 fixture.
"""

from __future__ import annotations

import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from conferge.core.store import GraphStore, connect_graph
from conferge.graph import queries as Q
from conferge.graph.bundle import ingest_bundle
from conferge.graph.explain import path_to_text
from conferge.graph.memory import record_memory
from conferge.graph.seed import load_graph_fixture, seed

OUT = Path(__file__).resolve().parents[2] / "probes" / "graph.md"
CONFERENCE = "github-universe-2026"
USER = "demo-user"
GOAL = "g-agent-founders"


def _endpoint() -> str:
    return f"{os.getenv('FALKORDB_HOST', '127.0.0.1')}:{os.getenv('FALKORDB_PORT', '6379')}"


def _memory_demo() -> dict[str, Any]:
    """Ranking before/after a MET memory, on a scratch graph that is deleted."""
    from falkordb import FalkorDB

    args: dict[str, Any] = {"host": os.getenv("FALKORDB_HOST", "127.0.0.1"),
                            "port": int(os.getenv("FALKORDB_PORT", "6379"))}
    if os.getenv("FALKORDB_PASSWORD"):
        args["password"] = os.environ["FALKORDB_PASSWORD"]
    db = FalkorDB(**args)
    scratch = db.select_graph("conferge_w08_probe_scratch")
    try:
        scratch.delete()
    except Exception:  # noqa: BLE001 - graph may not exist yet
        pass
    scratch_store = GraphStore(scratch)
    ingest_bundle(scratch_store, load_graph_fixture())
    before = [r["person_id"] for r in Q.people_for_goal(scratch_store, USER, GOAL)["rows"]]
    met = before[0] if before else None
    if met:
        record_memory(scratch_store, USER, "MET", "Person", met, note="probe")
    after = [r["person_id"] for r in Q.people_for_goal(scratch_store, USER, GOAL)["rows"]]
    scratch.delete()
    return {"before": before, "met": met, "after": after}


def run() -> tuple[str, list[str]]:
    started = datetime.now(timezone.utc)
    lines = [
        "# Probe w08 graph (FalkorDB)",
        "",
        f"- collected_at: {started.isoformat()}",
        f"- endpoint: {_endpoint()} graph `{os.getenv('FALKORDB_GRAPH', 'conferge')}`",
        "- source: FalkorDB round-trip is **live**; graph data is **fixture** "
        "(`fixtures/graph.json`, fictional people/events labelled `Fixture`/`[FIXTURE]`; "
        "conference anchor from docs/knowledge/03-demo-scenario.md)",
    ]
    errors: list[str] = []
    try:
        store = connect_graph()
        t0 = time.perf_counter()
        seeded = seed(store)
        seed_ms = int((time.perf_counter() - t0) * 1000)
    except Exception as exc:  # noqa: BLE001 - probe reports any connection failure
        errors.append(f"{type(exc).__name__}: {exc}")
        lines += ["- status: **failed** (termination: error)", "", "## Errors", "",
                  *[f"- {e}" for e in errors],
                  "", "No graph data was written; nothing below is substituted."]
        return "\n".join(lines) + "\n", errors

    counts = Q.graph_counts(store)
    people = Q.people_for_goal(store, USER, GOAL)
    events = Q.events_for_goal(store, USER, GOAL)
    clashes = Q.conflicts(store, CONFERENCE)
    top = people["rows"][0]["person_id"] if people["rows"] else None
    route = Q.path_user_to_person(store, USER, top) if top else {"rows": [], "paths": []}
    ui = Q.graph_for_ui(store, CONFERENCE)
    try:
        memory = _memory_demo()
    except Exception as exc:  # noqa: BLE001
        memory = None
        errors.append(f"memory demo: {type(exc).__name__}: {exc}")

    warnings = seeded["graph.json"]["warnings"]
    multi_hop = [r for r in people["rows"] if r["shortest_hops"] and 2 <= r["shortest_hops"] <= 4]
    status = "ok" if not errors and len(multi_hop) >= 5 else "degraded"
    lines += [
        f"- status: **{status}** (termination: {'exhausted' if status == 'ok' else 'error'})",
        f"- seed: {seeded['graph.json']['nodes']} node merges, "
        f"{seeded['graph.json']['edges']} edge merges in {seed_ms} ms",
        f"- node counts: {counts['nodes']}",
        f"- edge counts: {counts['edges']}",
        f"- UI subgraph: {ui['rows'][0]}",
        "",
        "## Ingest warnings (edges refused, not invented)",
        "",
        *([f"- {w}" for w in warnings] or ["- none"]),
        "",
        f"## people_for_goal({USER}, {GOAL})",
        "",
        f"{len(multi_hop)} people reachable with a 2 to 4 hop path (acceptance: >= 5).",
        "",
        "| person | score | reasons | paths | shortest hops |",
        "|---|---|---|---|---|",
        *[f"| {r['name']} | {r['score']} | {', '.join(r['reasons'])} | {r['path_count']} "
          f"| {r['shortest_hops']} |" for r in people["rows"]],
        "",
        "Example explanations (first path per person):",
        "",
    ]
    seen: set[str] = set()
    for path in people["paths"]:
        pid = path["nodes"][-1]["id"]
        if pid not in seen:
            seen.add(pid)
            lines.append(f"- {path_to_text(path)}")
    lines += [
        "",
        f"## events_for_goal({USER}, {GOAL})",
        "",
        *[f"- {r['title']} ({r['start_at'] or 'time not published'}): "
          f"{r['target_people_count']} target people, basis {r['presence_basis']}"
          for r in events["rows"]],
        "",
        f"## conflicts({CONFERENCE})",
        "",
        *[(f"- overlap: {c['a']['title']} x {c['b']['title']}, distance "
           f"{c['distance_m'] if c['distance_m'] is not None else 'unknown'} m")
          if c["kind"] == "overlap" else f"- unverifiable: {c['a']['title']} ({c['reason']})"
          for c in clashes["rows"]],
        "",
        f"## path_user_to_person({USER}, {top})",
        "",
        *[f"- {row['goal_id']} ({row['hops']} hops): {path_to_text(path)}"
          for row, path in zip(route["rows"], route["paths"], strict=True)],
        "",
        "## Cross-session memory (scratch graph, deleted after)",
        "",
    ]
    if memory:
        lines += [f"- ranking before: {memory['before']}",
                  f"- recorded MET with: {memory['met']}",
                  f"- ranking after: {memory['after']}"]
    if errors:
        lines += ["", "## Errors", "", *[f"- {e}" for e in errors]]
    return "\n".join(lines) + "\n", errors


def main() -> int:
    text, errors = run()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text, encoding="utf-8")
    print(text)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
