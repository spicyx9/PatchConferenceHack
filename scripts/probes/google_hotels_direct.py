"""Google Hotels direct (no key, swoop-hotels method): ONE page fetch, recorded in data/cache/stays.json.

San Francisco 2026-10-27 -> 2026-10-30, 2 adults, USD, at most 15 hotels, 20 s timeout, no
retry. Hotels whose page echoes the requested stay are appended to data/cache/stays.json
(labelled google_hotels_direct, after the Bright Data datasets); the run itself (records,
status, reason) is recorded in the file's ``runs`` for the Data pipeline panel. A blocked
or empty page changes nothing but that run row. ``--from-html PATH`` replays a page already
fetched (no new request). ``--brightdata-run`` also records the Bright Data Google Hotels
dataset outcome given as ``status,records,reason,collected_at``.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from conferge.integration import travel_cache  # noqa: E402
from conferge.lodging import google_hotels_direct as ghd  # noqa: E402
from conferge.lodging.models import LodgingQuery  # noqa: E402
from conferge.lodging.normalize import normalize  # noqa: E402

QUERY = LodgingQuery(check_in=date(2026, 10, 27), check_out=date(2026, 10, 30), adults=2,
                     currency="USD", limit=ghd.MAX_HOTELS, verify_top=0)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--from-html", type=Path, default=None)
    ap.add_argument("--collected-at", default=None, help="ISO time of the replayed fetch")
    ap.add_argument("--brightdata-run", default=None)
    args = ap.parse_args()

    if args.brightdata_run:
        status, records, reason, at = args.brightdata_run.split(",", 3)
        travel_cache.add_run("stays", {"provider": "google_hotels", "api": "dataset",
                                       "status": status, "records": int(records),
                                       "reason": reason, "collected_at": at})
    fetch = None
    clock = None
    if args.from_html:
        html = args.from_html.read_text(encoding="utf-8")
        fetch = lambda url, timeout: html  # noqa: E731 - replay, no request
        if args.collected_at:
            at = datetime.fromisoformat(args.collected_at)
            clock = lambda: at  # noqa: E731
    source = ghd.GoogleHotelsDirectSource(fetch=fetch, **({"clock": clock} if clock else {}))
    result = asyncio.run(source.search(QUERY))
    rep = result.run_report
    stays = [s for r in result.items if (s := normalize(r, QUERY, warnings=[])) is not None]
    if stays:
        path = travel_cache.CACHE_DIR / travel_cache.FILES["stays"]
        doc = json.loads(path.read_text(encoding="utf-8"))
        doc["records"] = [r for r in doc["records"]
                          if r["record"].get("provider") != ghd.PROVIDER]
        doc["records"] += [{"provenance": travel_cache.provenance(s),
                            "record": json.loads(s.model_dump_json())} for s in stays]
        doc["sources"] = sorted({*doc.get("sources", []), "google_hotels_direct page"})
        path.write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
    travel_cache.add_run("stays", {
        "provider": ghd.PROVIDER, "api": "direct", "status": rep.status, "records": len(stays),
        "reason": rep.errors[0] if rep.errors else None,
        "collected_at": args.collected_at or rep.finished_at.astimezone(timezone.utc).isoformat()})
    print(f"google_hotels_direct: {rep.status}, {len(stays)} stays; {rep.errors or rep.warnings}")
    for s in stays[:5]:
        print(f"  {s.name}: {s.total_price or s.nightly_avg} {s.currency} {s.price_status}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
