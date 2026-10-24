"""Crunchbase funding refresh (Bright Data SERP + Crunchbase dataset), out of the demo path.

Run: ``make probe-crunchbase`` (``uv run python scripts/probes/crunchbase.py [--force]
[--graph NAME] [--dry-run]``). Spends Bright Data credits: at most 10 SERP requests and ONE
dataset collection of at most 10 URLs. Refuses a second run on the same UTC day (the raw
file ``data/probes/crunchbase_<YYYY-MM-DD>.json`` exists) unless ``--force``.

1. assemble the demo data like ``make demo`` (fixture sources);
2. rank people: ``conferge.graph.ranking.rank_people`` on a probe FalkorDB graph when one
   answers, else the planner opportunities (as ``run_demo.py --no-graph``); read-only;
3. ``select_companies``: companies of the top 20 ranked speakers, at most 10;
4. one SERP lookup per company (``"<name>" site:crunchbase.com/organization``, brd_json=1);
5. one dataset collection for every URL found, normalize, write the raw rows and the public
   cache ``data/cache/crunchbase_public.json``, and the Company nodes through GraphStore;
6. print found/N, examples and any cost field Bright Data returned. Writes probes/crunchbase.md.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from conferge.people import crunchbase as cb  # noqa: E402

OUT = ROOT / "probes" / "crunchbase.md"


def _ranked(assembly, goals, graph: str):  # type: ignore[no-untyped-def]
    from conferge.core.store import connect_graph_or_none

    os.environ["FALKORDB_GRAPH"] = graph
    store = connect_graph_or_none()
    if store is not None:
        from conferge.graph import GraphBundle, ingest_bundle, ranking

        try:
            store.graph.delete()
        except Exception:  # noqa: BLE001 - absent graph
            pass
        from conferge.core.store import connect_graph

        store = connect_graph()
        store.ensure_indexes(force=True)
        ingest_bundle(store, GraphBundle(
            source_mode="fixture", note="scripts/probes/crunchbase.py",
            conference=assembly.conference, companies=assembly.companies,
            people=assembly.people, events=assembly.events, goals=goals))
        ranked = [pid for o in ranking.rank_people(store, "demo-user", goals) for pid in o.person_ids]
        return ranked, store, "graph ranking (conferge.graph.ranking.rank_people)"
    from conferge.integration import pipeline

    report = pipeline.E2EReport(mode="fixture", started_at=datetime.now(timezone.utc))
    opps = asyncio.run(pipeline._stage_planning(report, assembly, goals))
    return [pid for o in opps for pid in o.person_ids], None, "planner opportunities (no FalkorDB)"


async def _collect(companies):  # type: ignore[no-untyped-def]
    from conferge.core.brightdata import BrightDataClient, BrightDataError

    found: dict[str, str] = {}
    misses: list[str] = []
    progress: dict = {}
    rows: list[dict] = []
    snapshot_id = None
    async with BrightDataClient.from_env() as client:
        for api in ("serp", "datasets"):
            if problem := client.not_ready(api):  # type: ignore[arg-type]
                raise SystemExit(f"probe-crunchbase: {problem}")
        for company in companies:
            try:
                url = await cb.find_crunchbase_url(client, company.name)
            except BrightDataError as exc:
                misses.append(f"{company.name}: SERP error {str(exc)[:120]}")
                continue
            if url:
                found[company.id] = url
            else:
                misses.append(f"{company.name}: no single clear crunchbase.com/organization hit")
        if found:
            try:
                rows, snapshot_id = await cb.fetch_company(client, list(found.values()),
                                                           progress_out=progress)
            except cb.CrunchbaseUnavailable as exc:
                misses.append(f"dataset collection failed: {exc}")
    return found, misses, rows, snapshot_id, progress


def _row_for(url: str, rows: list[dict]) -> dict | None:
    for row in rows:
        if row.get("error"):
            continue
        for key in ("url", "input_url", "crunchbase_url"):
            value = row.get(key)
            if isinstance(value, str) and cb.canonical_org_url(value) == url:
                return row
        inp = row.get("input")
        if isinstance(inp, dict) and isinstance(inp.get("url"), str) \
                and cb.canonical_org_url(inp["url"]) == url:
            return row
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--force", action="store_true", help="run again on the same day")
    parser.add_argument("--graph", default="conferge_crunchbase_probe")
    parser.add_argument("--dry-run", action="store_true",
                        help="select companies and stop (no Bright Data call)")
    args = parser.parse_args()

    today = datetime.now(timezone.utc).date().isoformat()
    raw_path = cb.PROBE_DIR / f"crunchbase_{today}.json"
    if raw_path.exists() and not args.force and not args.dry_run:
        print(f"probe-crunchbase: already ran today ({raw_path.relative_to(ROOT)} exists); "
              "pass --force to spend credits again", file=sys.stderr)
        return 3

    from conferge.api.logic import parse_goals
    from conferge.integration import pipeline
    from conferge.integration.assemble import assemble

    t0 = time.perf_counter()
    slices = asyncio.run(pipeline._collect("fixture", False, 90.0, None))
    assembly = assemble(pipeline._usable(slices), None)
    goals = parse_goals(assembly.demo.demo_goal_text)
    ranked, store, how = _ranked(assembly, goals, args.graph)
    companies = cb.select_companies(ranked, assembly.people, assembly.companies)
    print(f"ranking: {how}; {len(ranked)} ranked people; {len(companies)} companies selected:")
    for c in companies:
        print(f"  - {c.id}: {c.name}")
    if args.dry_run or not companies:
        return 0

    found, misses, rows, snapshot_id, progress = asyncio.run(_collect(companies))
    collected_at = datetime.now(timezone.utc)
    # Always written once credits were spent: it is also the same-day guard.
    cb.write_raw(rows, snapshot_id=snapshot_id, collected_at=collected_at)
    entries, examples, written = [], [], 0
    for company in companies:
        url = found.get(company.id)
        row = _row_for(url, rows) if url else None
        if row is None:
            continue
        funding = cb.normalize(row)
        investor = cb.is_investor(row, company.name)
        entries.append(cb.public_entry(company, url, funding, snapshot_id=snapshot_id,
                                       collected_at=collected_at))
        examples.append(f"{company.name}: total {funding['total_funding_usd'] or '-'} USD, "
                        f"last {funding['last_round_type'] or '-'} "
                        f"{funding['last_round_date'] or ''}, investors "
                        f"{len(funding['investors'])}, investor={investor}")
        if store is not None:
            cb.write_company(store, company.id, funding, crunchbase_url=url,
                             snapshot_id=snapshot_id, collected_at=collected_at,
                             investor=investor)
            written += 1
    if entries:
        cb.write_public_cache(entries)
    cost = {k: v for k, v in progress.items() if re.search(r"cost|price|charge|credit", k, re.I)}
    lines = [
        f"# Probe: Crunchbase funding (Bright Data dataset {cb.dataset_id()})", "",
        f"- run at: {collected_at.isoformat()} ({time.perf_counter() - t0:.1f} s), live",
        f"- ranking: {how}",
        f"- URLs found via SERP: {len(found)}/{len(companies)}",
        f"- dataset rows: {len(rows)} ({sum(1 for r in rows if r.get('error'))} error rows), "
        f"snapshot {snapshot_id}",
        f"- normalized companies: {len(entries)}/{len(companies)}; graph writes: {written}",
        f"- cost returned by the API: {cost or 'none (no cost field in the progress body)'}",
        "", "## Examples", "", *[f"- {e}" for e in examples[:10]],
        "", "## Not found", "", *[f"- {m}" for m in misses], "",
    ]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
