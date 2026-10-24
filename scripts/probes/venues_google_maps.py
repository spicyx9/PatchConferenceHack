"""Probe: venues of the demo plan through the Bright Data Google Maps dataset (one collection).

Reads the plan from a running demo API (``--api``, default http://127.0.0.1:8000), builds at most
15 venues (Fort Mason + side-event venues kept in the plan, deduplicated by name + city), runs one
dataset collection (one trigger, poll every 2 s, 180 s timeout) and writes:
  data/probes/venues_google_maps_<timestamp>.json  raw records (git-ignored)
  data/cache/venues.json                           public fields per venue (committed)
Run: ``uv run python scripts/probes/venues_google_maps.py [--api URL]``
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from conferge.core.brightdata import BrightDataClient  # noqa: E402
from conferge.venues import google_maps as gm  # noqa: E402


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", default="http://127.0.0.1:8000")
    parser.add_argument("--snapshot", help="read an existing snapshot instead of triggering (no new collection)")
    args = parser.parse_args()
    base = args.api.rstrip("/") + "/api/v1"
    with httpx.Client(timeout=30) as http:
        plan = http.get(f"{base}/plan").json()["plan"]
        events = http.get(f"{base}/events").json()["items"]
        conference = http.get(f"{base}/conference").json()["conference"]
    venues = gm.plan_venues(plan, events, conference)
    print(f"{len(venues)} venues: {[v['query_name'] for v in venues]}")
    async with BrightDataClient.from_env() as client:
        if args.snapshot:
            records, run = await gm.read_snapshot(client, args.snapshot, len(venues))
        else:
            records, run = await gm.collect(client, venues, conference)
    entries = gm.match(venues, records, snapshot_id=run["snapshot_id"], collected_at=run["finished_at"])
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    raw = ROOT / "data" / "probes" / f"venues_google_maps_{stamp}.json"
    raw.parent.mkdir(parents=True, exist_ok=True)
    raw.write_text(json.dumps({"run": run, "inputs": gm.inputs_for(venues, conference), "records": records},
                              indent=1, ensure_ascii=False))
    gm.write_cache(entries, run)
    found = sum(e["found"] for e in entries)
    print(f"run {run['status']} snapshot {run['snapshot_id']} records {run['records']}: "
          f"{found} of {len(entries)} venues found")
    for e in entries:
        print(f"  {'OK ' if e['found'] else '-- '}{e['query_name']} -> {e['name']} | {e['address']} | "
              f"{e['lat']},{e['lng']} | rating {e['rating']} ({e['reviews_count']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
