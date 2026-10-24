"""Serve the demo API and front on the assembled data, with the same data loaded into FalkorDB.

The default ``conferge.api.app:app`` serves ``fixtures/api.json`` (fictional people), whose ids
do not exist in the assembled graph. This launcher assembles events/people/companies (fixture
or live public sources), runs the planner agents, loads that bundle into FalkorDB through
GraphStore, and serves the API on the same ``DemoData`` so API and graph ids match.

Startup never starts a Bright Data collection. Stays and flights come from data/cache/
(normalized records of earlier Bright Data collections, labelled cached with their own
collected_at) when it exists, else from the API fixture; ``--travel live`` searches them live
(w05, w06) with the fixture as visible fallback.
LinkedIn profiles are read from data/probes/linkedin_*.json (< 24 h), written by
``make probe-linkedin`` (scripts/probes/linkedin.py); without those files nothing is enriched.

``--keep-graph`` serves on the graph as it is (no reset, no reload): restarting the API
process this way keeps what the session wrote to FalkorDB (meetings, skips).

Run: ``uv run python scripts/run_demo.py [--mode fixture|live] [--travel cached|live|fixture] [--graph conferge_demo] [--port 8000] [--keep-graph]``
FalkorDB address: FALKORDB_HOST / FALKORDB_PORT from the env or .env (default 127.0.0.1:6379).
Startup check: the port must answer GRAPH.LIST; a plain Redis or a closed port stops with one line.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def falkordb_preflight() -> str | None:
    """None when FALKORDB_HOST:FALKORDB_PORT answers GRAPH.LIST, else a one-line reason."""
    import redis

    from conferge.core.settings import env_value, falkordb_address

    host, port = falkordb_address()
    client = redis.Redis(host=host, port=port, password=env_value("FALKORDB_PASSWORD") or None,
                         socket_timeout=3, socket_connect_timeout=3)
    try:
        client.execute_command("GRAPH.LIST")
    except redis.ResponseError as exc:
        if "unknown command" in str(exc).lower():
            return f"port {port} is a plain Redis, set FALKORDB_PORT to the FalkorDB port"
        return f"FalkorDB at {host}:{port} refused GRAPH.LIST: {str(exc)[:120]}"
    except redis.RedisError as exc:
        return (f"nothing answers on {host}:{port} ({type(exc).__name__}); run `make up`, "
                "or set FALKORDB_PORT to the FalkorDB port")
    finally:
        client.close()
    return None


def linkedin_enrichment(args: argparse.Namespace, assembly: Any, goals: list[Any], store: Any,
                        ranked: list[str] | None = None) -> None:
    """Bright Data LinkedIn profiles onto the best ranked speakers (+ fixture hosts).

    Profiles come from data/probes/linkedin_*.json younger than 24 h (downloaded snapshots
    first), else from the committed public cache data/cache/linkedin_public.json: startup
    never calls Bright Data. ``make probe-linkedin`` refreshes both. Writes go through
    GraphStore only.
    """
    from conferge.integration import people_linkedin as li
    from conferge.integration.pipeline_view import row

    started = datetime.now(timezone.utc)
    if ranked is None:
        from conferge.graph import ranking

        ranked = [pid for o in ranking.rank_people(store, "demo-user", goals) for pid in o.person_ids]
    targets = li.select_targets(ranked, assembly.people, li.fixture_hosts(),
                                speakers=args.linkedin_speakers, host_count=args.linkedin_hosts)
    known = {p.id for p in assembly.people}
    res = asyncio.run(li.enrich([p for p in targets if p.id in known], assembly.companies, store,
                                allow_collect=False))
    if not res.enrichments:
        print(f"  linkedin: {len(targets)} targets, no usable profile in data/probes or "
              f"data/cache (make probe-linkedin fills them) {res.errors[:1]}")
        return
    assembly.demo.people = li.apply_to_people(assembly.demo.people, res.enrichments)
    assembly.demo.linkedin = li.cards(res.enrichments)
    report = li.run_report(started, targets=len(targets), written=len(res.enrichments),
                           source_mode=res.source_mode, errors=res.errors)
    assembly.demo.pipeline.append(row("linkedin", report))
    print(f"  linkedin ({res.source_mode}): {len(targets)} targets, {res.from_files} from files, "
          f"{len(res.enrichments)} matched, {len(res.unmatched)} name mismatch, "
          f"{len(res.absent_after)} missing; graph "
          f"{len(res.written.persons_written) if res.written else 0} persons, "
          f"{len(res.written.works_at) if res.written else 0} WORKS_AT "
          f"({len(res.written.works_at_corroborated) if res.written else 0} corroborated)")


def port_preflight(host: str, port: int) -> str | None:
    """None when the UI port can be bound, else a one-line reason (checked before collecting)."""
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind((host, port))
        except OSError:
            return f"port {port} is already in use, run `make demo DEMO_PORT={port + 1}`"
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--mode", choices=["fixture", "live"], default="fixture")
    parser.add_argument("--graph", default="conferge_demo", help="FalkorDB graph name")
    parser.add_argument("--reset-graph", action="store_true",
                        help="delete the graph first (drops the user's MET/SKIPPED memory)")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--no-graph", action="store_true", help="serve without loading FalkorDB")
    parser.add_argument("--keep-graph", action="store_true",
                        help="serve on the existing graph without resetting or reloading it")
    parser.add_argument("--travel", choices=["cached", "live", "fixture"], default=None,
                        help="stays/flights: cached (default when data/cache/ has them: earlier "
                             "Bright Data records, no call at startup), fixture, or live search "
                             "with fixture fallback")
    parser.add_argument("--travel-timeout", type=float, default=150.0,
                        help="seconds for live stays/flights (Bright Data snapshots are slow)")
    parser.add_argument("--linkedin", choices=["cached", "off"], default="cached",
                        help="LinkedIn enrichment from data/probes/linkedin_*.json (< 24 h), never "
                             "a Bright Data call; refresh with make probe-linkedin")
    parser.add_argument("--linkedin-speakers", type=int, default=10,
                        help="best ranked speakers with a linkedin_url to enrich")
    parser.add_argument("--linkedin-hosts", type=int, default=5,
                        help="hosts of fixtures/people.json with a linkedin_url to enrich")
    args = parser.parse_args()
    os.environ["FALKORDB_GRAPH"] = args.graph  # the API reads the same graph it was loaded into
    if problem := port_preflight(args.host, args.port):
        print(f"make demo: {problem}", file=sys.stderr)
        return 2
    if not args.no_graph and (problem := falkordb_preflight()):
        print(f"make demo: {problem}", file=sys.stderr)
        return 2

    import uvicorn

    from conferge.api.app import create_app
    from conferge.api.logic import parse_goals
    from conferge.graph import GraphBundle, ingest_bundle
    from conferge.integration import pipeline
    from conferge.integration.assemble import assemble
    from conferge.integration.stays_flights import collect_stays_flights

    t0 = time.perf_counter()
    report = pipeline.E2EReport(mode=args.mode, started_at=datetime.now(timezone.utc))
    timings = report.timings
    from conferge.integration import travel_cache

    with timings.step("collect"):
        slices = asyncio.run(pipeline._collect(args.mode, False, 90.0, None))
        if args.travel is None:
            args.travel = "cached" if travel_cache.available() else "fixture"
        if args.travel == "live":
            travel = asyncio.run(collect_stays_flights(args.travel_timeout))
        elif args.travel == "cached":
            travel = travel_cache.load()
        else:
            travel = None
    with timings.step("assemble"):
        usable_slices = pipeline._usable(slices)
        assembly = assemble(usable_slices, travel)
    goals = parse_goals(assembly.demo.demo_goal_text)
    with timings.step("plan"):
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

    if args.keep_graph:
        print(f"graph {args.graph}: kept as is (--keep-graph), not reset or reloaded")
    elif not args.no_graph:
        from conferge.core.store import connect_graph

        store = connect_graph()
        if args.reset_graph:
            try:
                store.graph.delete()
            except Exception:  # noqa: BLE001 - absent graph
                pass
            store = connect_graph()
        # Without --reset-graph the load is MERGE-only: memory survives a restart.
        index_errors = store.ensure_indexes(force=True)
        bundle = GraphBundle(
            source_mode="live" if assembly.data_mode == "live" else "fixture",
            note=f"scripts/run_demo.py, data_mode={assembly.data_mode}",
            conference=assembly.conference, companies=assembly.companies,
            people=assembly.people, events=assembly.events, goals=goals,
            opportunities=[o for o in opps if set(o.goal_ids) <= {g.id for g in goals}],
            lodging=assembly.demo.stays, flights=assembly.demo.flights,
        )
        t1 = time.perf_counter()
        with timings.step("ingest"):
            ingest = ingest_bundle(store, bundle)
        print(f"graph {args.graph}: {ingest.nodes} node writes, {ingest.edges} edge writes, "
              f"{len(ingest.skipped_edges)} skipped, in {time.perf_counter() - t1:.2f}s")
        states = {(i["label"], s) for i in store.index_status() for s in [i["status"]]}
        print(f"indexes: {len(states)} labels, status {sorted({s for _, s in states})}"
              + (f", errors: {index_errors}" if index_errors else ""))
        if args.linkedin != "off":
            linkedin_enrichment(args, assembly, goals, store)
    elif args.linkedin != "off":
        linkedin_enrichment(args, assembly, goals, None, ranked=[
            pid for o in opps for pid in o.person_ids])

    pipeline.record_collection(assembly.demo, slices, timings, report.started_at)
    app = create_app(data=assembly.demo)
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
