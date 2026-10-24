"""LinkedIn enrichment refresh (Bright Data), out of the demo startup path: writes probes/linkedin.md.

Run: ``make probe-linkedin`` (``uv run python scripts/probes/linkedin.py [--snapshot ID ...]
[--no-collect] [--graph NAME]``).

1. assemble the demo data like ``make demo`` (fixture sources) and load it into a probe graph;
2. download the given existing snapshots (``GET /datasets/v3/snapshot/<id>?format=json``) to
   ``data/probes/linkedin_<id>.json`` (kept if already there);
3. targets: the 10 best ranked speakers with a linkedin_url + 5 hosts of fixtures/people.json
   with one; profiles from the saved files first, one new collection only for the targets they
   miss and only if more than 3 are missing (``--no-collect``: never);
4. write through GraphStore, report counts, people_for_goal top 5 before / after, and any cost
   Bright Data returned. ``make demo`` then reads the files, without calling Bright Data.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from conferge.integration import people_linkedin as li  # noqa: E402

OUT = ROOT / "probes" / "linkedin.md"
SNAPSHOTS = ("sd_mvmpuno1cydgpjvik", "sd_mvmpunm2ess6r1ual")


def _top(rows: list[dict]) -> list[str]:
    return [f"{i}. {r['name']} ({r['person_id']}) score {r['score']}" for i, r in enumerate(rows, 1)]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--snapshot", action="append", help="existing snapshot id to download")
    parser.add_argument("--no-collect", action="store_true", help="never start a new collection")
    parser.add_argument("--graph", default="conferge_linkedin_probe")
    args = parser.parse_args()

    import os

    os.environ["FALKORDB_GRAPH"] = args.graph
    from conferge.api.logic import parse_goals
    from conferge.core.store import connect_graph
    from conferge.graph import GraphBundle, ingest_bundle, ranking
    from conferge.graph.queries import people_for_goal
    from conferge.integration import pipeline
    from conferge.integration.assemble import assemble

    t0 = time.perf_counter()
    slices = asyncio.run(pipeline._collect("fixture", False, 90.0, None))
    assembly = assemble(pipeline._usable(slices), None)
    goals = parse_goals(assembly.demo.demo_goal_text)
    store = connect_graph()
    try:
        store.graph.delete()
    except Exception:  # noqa: BLE001 - absent graph
        pass
    store = connect_graph()
    store.ensure_indexes(force=True)
    ingest_bundle(store, GraphBundle(
        source_mode="fixture", note="scripts/probes/linkedin.py", conference=assembly.conference,
        companies=assembly.companies, people=assembly.people, events=assembly.events, goals=goals))
    goal = goals[0]
    before = people_for_goal(store, "demo-user", goal.id, 5)["rows"]
    ranked = [pid for o in ranking.rank_people(store, "demo-user", goals) for pid in o.person_ids]

    snapshots = []
    for sid in args.snapshot or SNAPSHOTS:
        path = li.PROBE_DIR / f"linkedin_{sid}.json"
        if path.exists():
            snapshots.append(f"- {sid}: kept {path.relative_to(ROOT)} (already downloaded)")
            continue
        got = asyncio.run(li.download_snapshot(sid))
        if got.records:
            li.save(got)
        snapshots.append(f"- {sid}: HTTP {got.http_status}, {got.status}, {len(got.records)} records"
                         + (f" -> {got.path.relative_to(ROOT)}" if got.path else "")
                         + (f"; errors {got.errors}" if got.errors else ""))

    known = {p.id for p in assembly.people}
    targets = [t for t in li.select_targets(ranked, assembly.people, li.fixture_hosts())
               if t.id in known]
    hosts_with_url = [h for h in li.fixture_hosts() if h.linkedin_url]
    res = asyncio.run(li.enrich(targets, assembly.companies, store,
                                allow_collect=not args.no_collect))
    if res.enrichments:  # keep the committed public cache in step with a fresh run
        li.write_public(res.enrichments)
    after = people_for_goal(store, "demo-user", goal.id, 5)["rows"]
    tagged = store.graph.query(
        "MATCH (p:Person {provider: 'brightdata:linkedin'}) RETURN count(p)").result_set[0][0]

    col = res.collection
    lines = [
        "# Probe: LinkedIn enrichment (Bright Data dataset gd_l1viktl72bvl7bjuj0)", "",
        f"- run at: {datetime.now(timezone.utc).isoformat()} ({time.perf_counter() - t0:.1f} s)",
        f"- graph: {args.graph} (demo data, fixture sources); goal: {goal.id}",
        f"- targets: {len(targets)} ({sum(t.participation == 'confirmed_speaker' for t in targets)}"
        f" speakers; hosts of fixtures/people.json with a linkedin_url: {len(hosts_with_url)})",
        "", "## Existing snapshots", "", *snapshots, "",
        "## Profiles", "",
        f"- from saved files (cached): {res.from_files}/{len(targets)}",
        f"- missing before collection: {len(res.absent_before)} "
        f"(new collection only when > {li.NEW_COLLECTION_MIN_MISSING - 1})",
    ]
    if col is None:
        lines.append("- new collection: none")
    else:
        lines += [f"- new collection: POST {li.ENDPOINT}, {len(col.inputs)} inputs, "
                  f"{col.requests} HTTP responses, last HTTP {col.http_status}, status {col.status}, "
                  f"snapshot {col.snapshot_id}, {len(col.records)} records -> "
                  f"{col.path.relative_to(ROOT) if col.path else '-'}",
                  f"- cost returned by the API: {col.cost or 'none (no cost header in the responses)'}"]
        if col.errors:
            lines.append(f"- collection errors: {col.errors}")
    lines += [
        f"- matched (name confirmed): {len(res.enrichments)}; name mismatch: {len(res.unmatched)}; "
        f"still missing: {len(res.absent_after)}",
        f"- identity_confidence 1.0: {sum(e.identity_confidence == 1.0 for e in res.enrichments)}, "
        f"0.7: {sum(e.identity_confidence == 0.7 for e in res.enrichments)}",
        "", "## FalkorDB writes (GraphStore MERGE)", "",
        f"- Person nodes written: {len(res.written.persons_written) if res.written else 0}; "
        f"nodes with provider brightdata:linkedin: {tagged}",
        f"- WORKS_AT edges: {len(res.written.works_at) if res.written else 0} (existing, kept their "
        f"provenance + LinkedIn corroboration: "
        f"{len(res.written.works_at_corroborated) if res.written else 0}); Company nodes created: "
        f"{len(res.written.companies_created) if res.written else 0}",
        "- no ATTENDS edge, no presence_confidence change (identity only)",
        "", "## people_for_goal top 5", "", "Before:", *_top(before), "", "After:", *_top(after), "",
    ]
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    store.graph.delete()
    return 0 if res.enrichments else 1


if __name__ == "__main__":
    raise SystemExit(main())
