"""Collect the Bright Data Google Flights dataset out of the demo path, then write a snapshot file.

The dataset (gd_mhng7wen1rw0a3gvpf) takes minutes, far over the demo's 120 s budget. This
script triggers ONE discover_by_input_filters request for JFK/EWR/LGA -> SFO (3 inputs,
round trip 2026-10-27 / 2026-10-30), waits up to 15 minutes, runs collect_by_url on the
candidate URLs that came back without itinerary data (one request, at most 20 inputs), and
writes data/snapshots/google_flights_<YYYY-MM-DD>.json with the dataset id, snapshot ids,
collected_at and every row (gitignored). The demo reads that file while it is < 24 h old
(conferge/flights/snapshot_provider.py). Nothing is relabelled or completed.

Run: ``uv run python scripts/probes/flights_collect.py`` (background friendly).
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from conferge.core.brightdata import BrightDataClient, BrightDataError, CollectionOutput  # noqa: E402
from conferge.flights.brightdata_provider import (  # noqa: E402
    DATASET_ID,
    build_input,
    has_itinerary_data,
)
from conferge.flights.snapshot_provider import SNAPSHOT_DIR  # noqa: E402

DEPART, RETURN = date(2026, 10, 27), date(2026, 10, 30)
ORIGINS = ("JFK", "EWR", "LGA")
WAIT_S = 15 * 60
POLL_S = 15
MAX_SYNC_INPUTS = 20


def log(msg: str) -> None:
    print(f"{datetime.now(timezone.utc).isoformat(timespec='seconds')} {msg}", flush=True)


async def _wait(client: BrightDataClient, out: CollectionOutput, deadline: float) -> CollectionOutput:
    while out.status == "running" and out.snapshot_id:
        if time.monotonic() >= deadline:
            raise BrightDataError(f"snapshot {out.snapshot_id} still running after {WAIT_S}s")
        await asyncio.sleep(POLL_S)
        out = await client.snapshot_results(out.snapshot_id)
        log(f"snapshot {out.snapshot_id}: {out.status}")
    return out


def _rows(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return [r for r in data if isinstance(r, dict)]
    if isinstance(data, dict):
        return [data]
    return []


async def main() -> int:
    deadline = time.monotonic() + WAIT_S
    inputs = [build_input(o, "SFO", DEPART, RETURN) for o in ORIGINS]
    result: dict[str, Any] = {"dataset_id": DATASET_ID, "inputs": inputs, "snapshots": [],
                              "status": "failed", "rows": [], "errors": []}
    async with BrightDataClient.from_env() as client:
        try:
            out = await client.scrape_dataset(DATASET_ID, inputs,
                                              method="discover_by_input_filters",
                                              limit_per_input=10)
            log(f"discover: {out.status} snapshot={out.snapshot_id}")
            out = await _wait(client, out, deadline)
            result["snapshots"].append({"kind": "discover", "snapshot_id": out.snapshot_id})
            rows = _rows(out.data)
            urls = [r["url"] for r in rows if not has_itinerary_data(r) and isinstance(r.get("url"), str)
                    and not (r.get("error") or r.get("error_code"))][:MAX_SYNC_INPUTS]
            if urls:
                more = await client.scrape_dataset(DATASET_ID, [{"url": u} for u in urls],
                                                   method="collect_by_url")
                log(f"collect_by_url ({len(urls)} urls): {more.status} snapshot={more.snapshot_id}")
                more = await _wait(client, more, deadline)
                result["snapshots"].append({"kind": "collect_by_url", "snapshot_id": more.snapshot_id})
                rows = [r for r in rows if has_itinerary_data(r)] + _rows(more.data)
            result["rows"] = rows
            result["status"] = "ready"
        except BrightDataError as exc:
            result["errors"].append(str(exc))
            log(f"failed: {exc}")
    result["collected_at"] = datetime.now(timezone.utc).isoformat()
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    path = SNAPSHOT_DIR / f"google_flights_{datetime.now(timezone.utc):%Y-%m-%d}.json"
    path.write_text(json.dumps(result, indent=1, default=str), encoding="utf-8")
    priced = sum(1 for r in result["rows"] if r.get("price") or r.get("pricing") or r.get("total_price"))
    log(f"wrote {path.relative_to(ROOT)}: {result['status']}, {len(result['rows'])} rows, "
        f"{priced} with a price field, snapshots {[s['snapshot_id'] for s in result['snapshots']]}")
    return 0 if result["status"] == "ready" else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
