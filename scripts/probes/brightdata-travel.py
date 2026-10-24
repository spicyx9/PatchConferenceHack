"""Probe: Bright Data first for the whole trip, one run per site, written to probes/brightdata-travel.md.

Stays: San Francisco 2026-10-27 -> 2026-10-30, 2 adults (Booking, Google Hotels and Airbnb
datasets + Web Unlocker search pages in parallel; pyairbnb only if they all return nothing).
Flights: JFK/EWR/LGA -> SFO, 2026-10-27 / 2026-10-30 (dataset -> Web Unlocker Google Flights
-> fast-flights per pair; one Unlocker page serves the three airports).
Each provider call is capped at 120 s. Raw envelopes go to raw/travel/ (gitignored).

``--resume booking=sd_x,google_hotels=sd_y,airbnb=sd_z`` downloads those already-produced
Bright Data snapshots instead of triggering new scrapes (one run per site: a run cut short
is finished from its snapshots, never re-scraped). ``--skip unlocker,flights`` leaves out
sources already run once today.
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
from collections import defaultdict
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from conferge.api.provenance import source_of  # noqa: E402
from conferge.core.brightdata import BrightDataClient, CollectionOutput, usage  # noqa: E402
from conferge.flights.dedupe import dedupe_offers  # noqa: E402
from conferge.flights.service import FlightSearchQuery, FlightService  # noqa: E402
from conferge.integration.stays_flights import pick_flights, pick_stays  # noqa: E402
from conferge.lodging.models import LodgingQuery  # noqa: E402
from conferge.lodging._common import (  # noqa: E402
    DATASET_AIRBNB,
    DATASET_BOOKING_SEARCH,
    DATASET_GOOGLE_HOTELS,
)
from conferge.lodging.service import LodgingService, default_sources  # noqa: E402

OUT = ROOT / "probes" / "brightdata-travel.md"
RAW = ROOT / "raw" / "travel"
TIMEOUT = 120.0
DEPART, RETURN = date(2026, 10, 27), date(2026, 10, 30)
PAIRS = [("JFK", "SFO"), ("EWR", "SFO"), ("LGA", "SFO")]
RESUME_KEYS = {"booking": DATASET_BOOKING_SEARCH, "google_hotels": DATASET_GOOGLE_HOTELS,
               "airbnb": DATASET_AIRBNB}


class SnapshotResumeClient(BrightDataClient):
    """Real client; for the given datasets it resumes an existing snapshot instead of scraping."""

    def __init__(self, resume: dict[str, str]) -> None:
        base = BrightDataClient.from_env()
        super().__init__(base._api_key, serp_zone=base.serp_zone,
                         unlocker_zone=base.unlocker_zone)
        self.resume = resume

    async def scrape_dataset(self, dataset_id, inputs, *, method=None, limit_per_input=10):
        if dataset_id in self.resume:
            return CollectionOutput(status="running", source_mode="live",
                                    snapshot_id=self.resume[dataset_id],
                                    warnings=[f"resumed snapshot {self.resume[dataset_id]}"])
        return await super().scrape_dataset(dataset_id, inputs, method=method,
                                            limit_per_input=limit_per_input)


def _args() -> tuple[dict[str, str], set[str]]:
    resume: dict[str, str] = {}
    skip: set[str] = set()
    argv = sys.argv[1:]
    for flag, value in zip(argv, argv[1:], strict=False):
        if flag == "--resume":
            for part in value.split(","):
                site, _, sid = part.partition("=")
                resume[RESUME_KEYS[site]] = sid
        elif flag == "--skip":
            skip = set(value.split(","))
    return resume, skip


async def _stays(resume: dict[str, str], skip: set[str]):
    from conferge.lodging.airbnb import AirbnbSource, BrightDataAirbnbBackend
    from conferge.lodging.booking import BookingSource
    from conferge.lodging.google_hotels import GoogleHotelsSource

    q = LodgingQuery(check_in=DEPART, check_out=RETURN, adults=2, currency="USD", limit=6,
                     verify_top=0, conference_id="github-universe-2026")
    sources = default_sources()
    if resume:
        client = SnapshotResumeClient(resume)
        sources.update({"booking": BookingSource(client), "google_hotels": GoogleHotelsSource(client),
                        "airbnb": AirbnbSource(primary=BrightDataAirbnbBackend(client),
                                               fallback=None)})
    for name in skip & set(sources):
        sources.pop(name)
    svc = LodgingService(sources, provider_timeout=TIMEOUT)
    try:
        return await svc.search(q)
    finally:
        await svc.aclose()


async def _flights(skip: set[str]):
    if "flights" in skip:
        return [], []
    svc = FlightService(provider_timeout=TIMEOUT)
    q = FlightSearchQuery(origin_city="New York", destination_city="San Francisco",
                          departure_date=DEPART, return_date=RETURN)
    results = await asyncio.gather(*(svc._search_pair(o, d, q) for o, d in PAIRS))
    offers = dedupe_offers(o for pair, _ in results for o in pair)
    reports = [r for _, reps in results for r in reps]
    return offers, reports


def _price(item) -> Decimal | None:
    if item.total_price is not None:
        return Decimal(str(item.total_price))
    return None


def _observed(item) -> Decimal | None:
    m = re.match(r"([0-9.]+)", getattr(item, "raw_price_text", None) or "")
    return Decimal(m.group(1)) if m else None


def _table(items, reports, kind: str) -> list[str]:
    rows: dict[str, list] = defaultdict(list)
    for item in items:
        rows[source_of(item.evidence)["label"]].append(item)
    lines = [f"### {kind}", "", "| provider / API | records | priced | price status | min | max |",
             "|---|---|---|---|---|---|"]
    for label, group in sorted(rows.items(), key=lambda kv: source_of(kv[1][0].evidence)["tier"]):
        prices = [p for p in map(_price, group) if p is not None]
        observed = [p for p in map(_observed, group) if p is not None]
        statuses = sorted({i.price_status for i in group})
        lo = f"{min(prices)}" if prices else (f"{min(observed)} (observed RT total)" if observed else "-")
        hi = f"{max(prices)}" if prices else (f"{max(observed)} (observed RT total)" if observed else "-")
        lines.append(f"| {label} | {len(group)} | {len(prices)} | {', '.join(statuses)} | {lo} | {hi} |")
    lines += ["", "Provider reports:", ""]
    for r in reports:
        pair = next((w for w in r.warnings if w.startswith("pair ")), "")
        errors = "; ".join(r.errors)[:220] or "none"
        lines.append(f"- `{r.provider}` {pair}: {r.status}/{r.termination}, fetched {r.fetched_count}; "
                     f"errors: {errors}")
    return lines + [""]


async def main() -> int:
    run_at = datetime.now(timezone.utc)
    resume, skip = _args()
    stays, (offers, flight_reports) = await asyncio.gather(_stays(resume, skip), _flights(skip))
    env = stays.envelope
    RAW.mkdir(parents=True, exist_ok=True)
    stamp = run_at.strftime("%Y%m%dT%H%M%SZ")
    (RAW / f"stays-{stamp}.json").write_text(env.model_dump_json(indent=1), encoding="utf-8")
    (RAW / f"flights-{stamp}.json").write_text(json.dumps(
        [json.loads(o.model_dump_json()) for o in offers], indent=1), encoding="utf-8")
    shown_stays, shown_flights = pick_stays(env.items), pick_flights(offers)
    lines = [
        "# Probe: Bright Data first, stays and flights", "",
        f"- run at: {run_at.isoformat()} (one run per site, {TIMEOUT:.0f} s cap per provider call)",
        "- stays: San Francisco 2026-10-27 -> 2026-10-30, 2 adults, USD; "
        "flights: JFK/EWR/LGA -> SFO 2026-10-27 / 2026-10-30, 1 adult economy",
        f"- stays envelope: {env.source_mode}/{env.status}, {len(env.items)} stays; "
        f"flights: {len(offers)} offers",
        f"- Bright Data usage in this run: {usage()}",
        f"- resumed snapshots: {resume or 'none'}; skipped: {sorted(skip) or 'none'}", "",
        *_table(env.items, env.reports, "Stays"),
        *_table(offers, flight_reports, "Flights"),
        "## Shown in the demo (integration pick)", "",
        *[f"- stay: {s.name} | {source_of(s.evidence)['label']} | {s.price_status} | "
          f"{s.total_price} {s.currency or ''}" for s in shown_stays],
        *[f"- flight: {o.trip_type} {o.slices[0].segments[0].origin_iata}->"
          f"{o.slices[-1].segments[-1].destination_iata} {o.slices[0].segments[0].departure_at} | "
          f"{source_of(o.evidence)['label']} | {o.price_status} | {o.total_price} {o.currency or ''}"
          for o in shown_flights],
        "", "Prices are what each source showed at collection time; nothing is estimated. "
        "Raw envelopes: raw/travel/ (gitignored).", "",
    ]
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}: {len(env.items)} stays, {len(offers)} flights")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
