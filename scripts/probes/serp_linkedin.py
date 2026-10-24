"""LinkedIn URL discovery by Bright Data SERP for speakers without one: writes probes/serp_linkedin.md.

Run: ``make probe-serp_linkedin`` (``uv run python scripts/probes/serp_linkedin.py
[--max 30] [--no-collect] [--zone serp_api1] [--graph NAME]``). Never part of demo startup.

1. assemble the demo data (fixture sources) into a probe graph;
2. targets: announced speakers with no linkedin_url (at most 30);
3. one SERP query each (conferge.integration.serp_linkedin), every lookup saved to
   data/probes/linkedin_serp_<ts>.json; found URLs written with brightdata:serp evidence;
4. one dataset batch (trigger + snapshot) for the found URLs, saved to
   data/probes/linkedin_<snapshot>.json; name-matched profiles corroborate identity and
   WORKS_AT, and their public fields are merged into data/cache/linkedin_public.json;
5. report counts and any cost header Bright Data returned. ``make demo`` then reads the cache.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
import time
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from conferge.integration import people_linkedin as li  # noqa: E402
from conferge.integration import serp_linkedin as serp  # noqa: E402

OUT = ROOT / "probes" / "serp_linkedin.md"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--max", type=int, default=serp.MAX_TARGETS)
    parser.add_argument("--no-collect", action="store_true", help="SERP only, no dataset batch")
    parser.add_argument("--zone", default=serp.SERP_ZONE)
    parser.add_argument("--graph", default="conferge_serp_probe")
    args = parser.parse_args()
    os.environ["FALKORDB_GRAPH"] = args.graph

    from conferge.api.logic import parse_goals
    from conferge.core.settings import env_value
    from conferge.core.store import connect_graph
    from conferge.graph import GraphBundle, ingest_bundle
    from conferge.integration import pipeline
    from conferge.integration.assemble import assemble

    key = env_value("BRIGHTDATA_API_KEY") or ""
    if not key:
        print("BRIGHTDATA_API_KEY missing: nothing sent", file=sys.stderr)
        return 2
    t0 = time.perf_counter()
    assembly = assemble(pipeline._usable(asyncio.run(pipeline._collect("fixture", False, 90.0, None))),
                        None)
    store = connect_graph()
    try:
        store.graph.delete()
    except Exception:  # noqa: BLE001 - absent graph
        pass
    store = connect_graph()
    store.ensure_indexes(force=True)
    ingest_bundle(store, GraphBundle(
        source_mode="fixture", note="scripts/probes/serp_linkedin.py", conference=assembly.conference,
        companies=assembly.companies, people=assembly.people, events=assembly.events,
        goals=parse_goals(assembly.demo.demo_goal_text)))
    names = {c.id: c.name for c in assembly.companies}
    targets = serp.targets_without_url(assembly.people, args.max)

    cost: dict[str, str] = {}

    async def remember(response: httpx.Response) -> None:
        cost.update({k: v for k, v in response.headers.items()
                     if re.search(r"cost|price|charge|billing|credit", k, re.I)})

    async def run() -> tuple[list[serp.Discovery], li.Collection | None]:
        async with httpx.AsyncClient(base_url="https://api.brightdata.com", timeout=60.0,
                                     event_hooks={"response": [remember]}) as http:
            found = await serp.discover(targets, names, api_key=key, http=http, zone=args.zone)
            cached = li.load_pool()  # profiles already collected: never billed twice
            urls = [d.linkedin_url for d in found if d.status == "found" and d.linkedin_url
                    and d.linkedin_url not in cached]
            batch = (None if args.no_collect or not urls
                     else await serp.collect_batch(urls, api_key=key, http=http))
            return found, batch

    discoveries, batch = asyncio.run(run())
    serp_path = serp.save(discoveries)
    url_writes = serp.write_urls(store, discoveries)
    people = serp.apply_urls(assembly.people, discoveries)
    by_url = {d.linkedin_url: d for d in discoveries if d.status == "found"}

    enrichments: list[li.Enrichment] = []
    unmatched: list[str] = []
    written = None
    if batch is not None:
        li.save(batch)
    pool = li.load_pool()
    profiles = []
    for url, d in by_url.items():
        pr = pool.get(url)
        if pr is not None:
            if not pr.headline and d.serp_headline:
                pr = replace(pr, headline=d.serp_headline, headline_source="serp:title")
            profiles.append(replace(pr, person_id=d.person_id, url_provider=serp.PROVIDER))
    if profiles:
        enrichments, unmatched = li.match([p for p in people if p.id in
                                           {d.person_id for d in by_url.values()}],
                                          assembly.companies, profiles)
        if enrichments:
            written = li.write(store, enrichments)
            li.write_public(enrichments, merge=True)

    found = [d for d in discoveries if d.status == "found"]
    lines = [
        "# Probe: LinkedIn URL discovery by Bright Data SERP", "",
        f"- run at: {datetime.now(timezone.utc).isoformat()} ({time.perf_counter() - t0:.1f} s)",
        f"- targets: {len(targets)} announced speakers without linkedin_url (max {args.max})",
        f"- SERP: zone {args.zone}, POST /request, google.com/search?...&brd_json=1&gl=us, "
        f"JSON organic only -> {serp_path.relative_to(ROOT)}",
        f"- URLs found: **{len(found)}/{len(targets)}**; not found: "
        f"{sum(d.status == 'not_found' for d in discoveries)}; failed: "
        f"{sum(d.status == 'failed' for d in discoveries)}",
        f"- Person.linkedin_url written (brightdata:serp): {len(url_writes)}",
    ]
    if batch is None:
        lines.append("- dataset batch: none (" + ("--no-collect" if args.no_collect
                                                   else "every found URL already in data/probes") + ")")
    else:
        lines += [
            f"- dataset batch: POST /datasets/v3/trigger, {len(batch.inputs)} inputs, snapshot "
            f"{batch.snapshot_id}, status {batch.status}, {len(batch.records)} rows",
            f"- private or hidden (warning_code): "
            f"{sum(1 for r in batch.records if r.get('warning_code') or r.get('warning'))}"]
        if batch.errors:
            lines.append(f"- batch errors: {batch.errors[:5]}")
    lines += [
            f"- profiles from data/probes for found URLs: {len(profiles)}",
            f"- profiles enriched (name confirmed): **{len(enrichments)}**; name mismatch: "
            f"{len(unmatched)}; headline from position: "
            f"{sum(e.profile.headline_source == 'dataset:position' for e in enrichments)}, "
            f"from SERP title: {sum(e.profile.headline_source == 'serp:title' for e in enrichments)}",
            f"- graph: {len(written.persons_written) if written else 0} Person, "
            f"{len(written.works_at) if written else 0} WORKS_AT "
            f"({len(written.works_at_corroborated) if written else 0} corroborated); no ATTENDS",
        ]
    lines += [f"- cost returned by the API: {cost or 'none (no cost header in the responses)'}",
              "", "## Lookups", "",
              "| speaker | company | verdict | score | reason |", "|---|---|---|---|---|"]
    for d in discoveries:
        reason = d.error or (d.reasons[-1] if d.reasons else "")
        lines.append(f"| {d.name} | {d.company or '-'} | {d.status} | "
                     f"{d.score if d.score is not None else '-'} | {reason} |")
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    store.graph.delete()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
