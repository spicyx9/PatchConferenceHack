"""Build data/cache/stays.json and data/cache/flights.json from earlier probe outputs. No network.

Inputs (local, gitignored probe outputs):
- ``--stays``: a normalized stays envelope written by scripts/probes/brightdata-travel.py
  (raw/travel/stays-*.json, DataEnvelope[Lodging] JSON);
- ``--flights-html``: a Google Flights search page fetched once through the Bright Data Web
  Unlocker, with ``--flights-url`` (the URL fetched), ``--flights-collected-at`` (ISO time of
  that fetch) and ``--zone`` (the Unlocker zone used).
Only normalized records are written (no HTML, no LinkedIn). Run:
``uv run python scripts/probes/build_travel_cache.py --stays ... --flights-html ... ...``
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from conferge.core.schemas import Lodging  # noqa: E402
from conferge.flights.unlocker_provider import offers_from_rows, parse_google_flights  # noqa: E402
from conferge.integration import travel_cache  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--stays", type=Path, required=True)
    ap.add_argument("--flights-html", type=Path, required=True)
    ap.add_argument("--flights-url", required=True)
    ap.add_argument("--flights-collected-at", required=True)
    ap.add_argument("--zone", required=True)
    ap.add_argument("--out", type=Path, default=travel_cache.CACHE_DIR)
    args = ap.parse_args()

    now = datetime.now(timezone.utc)
    env = json.loads(args.stays.read_text(encoding="utf-8"))
    stays = [Lodging.model_validate(i) for i in env["items"]]
    collected = datetime.fromisoformat(args.flights_collected_at)
    rows = parse_google_flights(args.flights_html.read_text(encoding="utf-8"), args.flights_url)
    flights, warnings = offers_from_rows(rows, args.flights_url, collected, args.zone)
    args.out.mkdir(parents=True, exist_ok=True)
    for domain, items, src in (("stays", stays, [args.stays.name]),
                               ("flights", flights, [f"web_unlocker {args.flights_url}"])):
        doc = travel_cache.build(domain, items, sources=src, generated_at=now)
        path = args.out / travel_cache.FILES[domain]
        path.write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
        print(f"wrote {path.relative_to(ROOT)}: {len(items)} records, collected {doc['collected_at']}")
    if warnings:
        print("flight warnings:", warnings[:5])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
