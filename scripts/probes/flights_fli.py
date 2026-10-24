"""Probe: Google Flights through fli (secondary source behind Bright Data Web Unlocker).

One attempt (no retry), 20 s, JFK-SFO 2026-10-27 / 2026-10-30, 1 adult, economy, at most 15
itineraries. Writes probes/flights_fli.md (with the 5 cheapest fli vs the 5 cheapest Web Unlocker
itineraries and any gap over 15 % on the same flight), data/cache/fli_run.json (read by the Data
pipeline panel) and, only when fli returns itineraries, adds them to data/cache/flights.json
behind the Web Unlocker records. Run: ``make probe-flights_fli``.
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from conferge.core.schemas import FlightOffer  # noqa: E402
from conferge.flights import fli_provider as fli  # noqa: E402
from conferge.flights.round_trip_total import trip_price  # noqa: E402
from conferge.flights.snapshot_provider import latest_snapshot  # noqa: E402
from conferge.integration import travel_cache  # noqa: E402

OUT_MD = ROOT / "probes" / "flights_fli.md"
RUN_FILE = travel_cache.CACHE_DIR / "fli_run.json"
GAP = Decimal("0.15")


def _flight_key(o: FlightOffer) -> tuple[str, ...]:
    return tuple(f"{s.flight_number or s.marketing_carrier}@{s.departure_at:%Y-%m-%dT%H:%M}"
                 for s in o.slices[0].segments)


def _line(o: FlightOffer) -> str:
    s = o.slices[0].segments
    price = trip_price(o)
    return (f"| {s[0].marketing_carrier} | {s[0].origin_iata} {s[0].departure_at:%m-%d %H:%M} -> "
            f"{s[-1].destination_iata} {s[-1].arrival_at:%H:%M} | {len(s) - 1} | "
            f"{price if price is not None else 'unknown'} |")


def main() -> int:
    offers, report = asyncio.run(fli.search_round_trip())
    cache_path = travel_cache.CACHE_DIR / travel_cache.FILES["flights"]
    doc = json.loads(cache_path.read_text(encoding="utf-8"))
    unlocker = [FlightOffer.model_validate(r["record"]) for r in doc["records"]
                if r["provenance"]["api"] == "unlocker"]
    snap, snap_reason = latest_snapshot()
    priced = lambda xs: sorted((o for o in xs if trip_price(o) is not None), key=trip_price)  # noqa: E731
    top_fli, top_unl = priced(offers)[:5], priced(unlocker)[:5]
    gaps = []
    by_key = {_flight_key(o): o for o in unlocker}
    for o in offers:
        u = by_key.get(_flight_key(o))
        a, b = trip_price(o), trip_price(u) if u else None
        if a is not None and b is not None and b > 0 and abs(a - b) / b > GAP:
            gaps.append(f"- {' + '.join(_flight_key(o))}: fli {a} vs Web Unlocker {b} "
                        f"({(a - b) / b:+.0%})")
    now = datetime.now(timezone.utc)
    run = {
        "provider": fli.PROVIDER, "run_at": now.isoformat(), "status": report.status,
        "records": len(offers), "errors": report.errors, "source_url": fli.search_url(
            "JFK", "SFO", date(2026, 10, 27), date(2026, 10, 30)),
        "google_flights": {
            "dataset": "ready" if snap else "pending",
            "dataset_detail": None if snap else snap_reason,
            "unlocker": len(unlocker), "fli": len(offers)},
    }
    RUN_FILE.write_text(json.dumps(run, indent=1) + "\n", encoding="utf-8")
    if offers:  # behind Web Unlocker: same file, ranked by source tier at pick time
        kept = [FlightOffer.model_validate(r["record"]) for r in doc["records"]
                if r["provenance"]["provider"] != fli.PROVIDER]
        new = travel_cache.build("flights", kept + offers,
                                 sources=[*doc["sources"], f"fli {run['source_url']}"],
                                 generated_at=now)
        cache_path.write_text(json.dumps(new, indent=1) + "\n", encoding="utf-8")
    lines = [
        "# Probe: Google Flights through fli (secondary source)", "",
        f"- run at: {now.isoformat()}; JFK-SFO 2026-10-27 / 2026-10-30, 1 adult, economy; "
        "one attempt, 20 s, at most 15 itineraries",
        f"- fli: {report.status}, {len(offers)} itineraries; errors: {report.errors or 'none'}",
        f"- Google Flights sources: Bright Data dataset {run['google_flights']['dataset']}"
        f"{' (' + snap_reason + ')' if not snap else ''}, Web Unlocker {len(unlocker)}, fli {len(offers)}",
        "", "## 5 cheapest, fli", "", "| airline | outbound | stops | price |", "|---|---|---|---|",
        *([_line(o) for o in top_fli] or ["| - | none | - | - |"]),
        "", "## 5 cheapest, Bright Data Web Unlocker (round-trip totals as observed)", "",
        "| airline | outbound | stops | price |", "|---|---|---|---|", *[_line(o) for o in top_unl],
        "", "## Same flight, price gap over 15 %", "", *(gaps or ["- none found"]), "",
    ]
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {OUT_MD.relative_to(ROOT)} and {RUN_FILE.relative_to(ROOT)}: fli {report.status}, "
          f"{len(offers)} itineraries")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
