"""Serve the demo API and front on the assembled data, with the same data loaded into FalkorDB.

The default ``conferge.api.app:app`` serves ``fixtures/api.json`` (fictional people), whose ids
do not exist in the assembled graph. This launcher assembles events/people/companies (fixture
or live public sources), runs the planner agents, loads that bundle into FalkorDB through
GraphStore, and serves the API on the same ``DemoData`` so API and graph ids match.

Stays and flights are searched live by default (w05 lodging, w06 flights; 90 s each).
A domain that fails or returns nothing falls back to the API fixture, labelled ``fixture``.
``--travel fixture`` skips the live travel searches.

Run: ``uv run python scripts/run_demo.py [--mode fixture|live] [--travel live|fixture] [--graph conferge_demo] [--port 8000]``
FalkorDB address: FALKORDB_HOST / FALKORDB_PORT from the env or .env (default 127.0.0.1:6379).
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--mode", choices=["fixture", "live"], default="fixture")
    parser.add_argument("--graph", default="conferge_demo", help="FalkorDB graph name (reset on start)")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--no-graph", action="store_true", help="serve without loading FalkorDB")
    parser.add_argument("--travel", choices=["live", "fixture"], default="live",
                        help="stays/flights: live search with fixture fallback, or fixture only")
    args = parser.parse_args()
    os.environ["FALKORDB_GRAPH"] = args.graph  # the API reads the same graph it was loaded into

    import uvicorn

    from conferge.api.app import create_app
    from conferge.api.logic import parse_goals
    from conferge.graph import GraphBundle, ingest_bundle
    from conferge.integration import pipeline
    from conferge.integration.assemble import assemble
    from conferge.integration.stays_flights import collect_stays_flights

    t0 = time.perf_counter()
    report = pipeline.E2EReport(mode=args.mode, started_at=datetime.now(timezone.utc))
    slices = asyncio.run(pipeline._collect(args.mode, False, 90.0, None))
    travel = asyncio.run(collect_stays_flights(90.0)) if args.travel == "live" else None
    assembly = assemble(pipeline._usable(slices), travel)
    goals = parse_goals(assembly.demo.demo_goal_text)
    opps = asyncio.run(pipeline._stage_planning(report, assembly, goals))
    print(f"assembled data_mode={assembly.data_mode}: {len(assembly.events)} events, "
          f"{len(assembly.people)} people, {len(opps)} opportunities "
          f"in {time.perf_counter() - t0:.1f}s")
    for s in slices:
        print(f"  source {s.name}: {s.source_mode}/{s.status} {s.count}")
    for name in ("stays", "flights"):
        d = assembly.demo.domains[name]
        print(f"  {name}: {d.source_mode}/{d.status} {len(getattr(assembly.demo, name))} "
              f"collected_at={d.collected_at.isoformat()}")
        for w in d.warnings:
            print(f"    - {w}")

    if not args.no_graph:
        from conferge.core.store import connect_graph

        store = connect_graph()
        try:
            store.graph.delete()
        except Exception:  # noqa: BLE001 - absent graph
            pass
        store = connect_graph()
        index_errors = store.ensure_indexes(force=True)  # the graph was just deleted
        bundle = GraphBundle(
            source_mode="live" if assembly.data_mode == "live" else "fixture",
            note=f"scripts/run_demo.py, data_mode={assembly.data_mode}",
            conference=assembly.conference, companies=assembly.companies,
            people=assembly.people, events=assembly.events, goals=goals,
            opportunities=[o for o in opps if set(o.goal_ids) <= {g.id for g in goals}],
            lodging=assembly.demo.stays, flights=assembly.demo.flights,
        )
        t1 = time.perf_counter()
        ingest = ingest_bundle(store, bundle)
        print(f"graph {args.graph}: {ingest.nodes} node writes, {ingest.edges} edge writes, "
              f"{len(ingest.skipped_edges)} skipped, in {time.perf_counter() - t1:.2f}s")
        states = {(i["label"], s) for i in store.index_status() for s in [i["status"]]}
        print(f"indexes: {len(states)} labels, status {sorted({s for _, s in states})}"
              + (f", errors: {index_errors}" if index_errors else ""))

    app = create_app(data=assembly.demo)
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
