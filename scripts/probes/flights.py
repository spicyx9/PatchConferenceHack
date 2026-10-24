"""make probe-flights: live diagnostic of every flight path, written to probes/flights.md.

Order: Bright Data Google Flights (discover_by=input_filters then
collect_by_url), fast-flights (public Google Flights page, via Bright Data SERP
zone when configured), SerpApi, then the explicitly labelled fixture. Raw
responses go to probes/raw/ (git-ignored). No result is ever relabelled.
"""

from __future__ import annotations

import asyncio
import json
import sys
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from conferge.core.schemas import FlightOffer, RunReport  # noqa: E402
from conferge.flights.brightdata_provider import DATASET_ID, BrightDataFlightsProvider  # noqa: E402
from conferge.flights.dedupe import group_by_itinerary  # noqa: E402
from conferge.flights.fastflights_provider import FastFlightsProvider  # noqa: E402
from conferge.flights.serpapi_provider import SerpApiFlightsProvider  # noqa: E402
from conferge.flights.service import load_fixture_offers  # noqa: E402

ORIGIN, DESTINATION = "JFK", "SFO"
DEPART, RETURN = date(2026, 10, 27), date(2026, 10, 30)
REPORT = ROOT / "probes" / "flights.md"
RAW_DIR = ROOT / "probes" / "raw"


def _save_raw(name: str, offers: list[FlightOffer], report: RunReport) -> str:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = RAW_DIR / f"flights-{name}-{stamp}.json"
    path.write_text(json.dumps({
        "report": json.loads(report.model_dump_json()),
        "offers": [json.loads(o.model_dump_json()) for o in offers],
    }, indent=1), encoding="utf-8")
    return str(path.relative_to(ROOT))


def _segment_text(offer: FlightOffer) -> str:
    parts = []
    for s in offer.slices:
        for seg in s.segments:
            dep = seg.departure_at.isoformat() if seg.departure_at else "unknown"
            arr = seg.arrival_at.isoformat() if seg.arrival_at else "unknown"
            parts.append(f"{seg.marketing_carrier or '?'}{'/' + seg.flight_number if seg.flight_number else ''} "
                         f"{seg.origin_iata} {dep} -> {seg.destination_iata} {arr}")
    return "; ".join(parts)


def _section(title: str, mode: str, offers: list[FlightOffer], report: RunReport,
             raw_ref: str | None) -> list[str]:
    missing = [e for e in report.errors if "key missing" in e.lower()
               or "serpapi_key missing" in e.lower() or "not installed" in e.lower()]
    verdict = ("missing_credentials" if missing and "not installed" not in missing[0]
               else "missing_dependency" if missing else report.status)
    lines = [f"## {title}", "",
             f"- probe verdict: **{verdict}**",
             f"- mode: **{mode}**",
             f"- status / termination: `{report.status}` / `{report.termination}`",
             f"- fetched (raw) / unique: {report.fetched_count} / {report.unique_count}; "
             f"normalized offers: {len(offers)}",
             f"- window: {report.started_at.isoformat()} -> {report.finished_at.isoformat()}"]
    if raw_ref:
        lines.append(f"- raw (git-ignored): `{raw_ref}`")
    if offers:
        priced = [o for o in offers if o.total_price is not None]
        trips = Counter(o.trip_type for o in offers)
        with_number = sum(1 for o in offers for s in o.slices for g in s.segments if g.flight_number)
        with_times = sum(1 for o in offers for s in o.slices for g in s.segments if g.departure_at)
        segs = sum(len(s.segments) for o in offers for s in o.slices)
        lines += [
            f"- trip types: {dict(trips)}; priced: {len(priced)}/{len(offers)}",
            f"- completeness: segments with flight number {with_number}/{segs}, "
            f"with timezone-aware departure {with_times}/{segs}",
            f"- itineraries (dedup groups): {len(group_by_itinerary(offers))}",
            f"- collected_at: {offers[0].collected_at.isoformat()}",
        ]
        sources = {str(e.source_url) for o in offers for e in o.evidence if e.source_url}
        for url in sorted(sources)[:3]:
            lines.append(f"- source: {url[:160]}")
        lines += ["", "Cheapest samples:", ""]
        for o in sorted(priced, key=lambda o: float(o.total_price))[:4]:
            lines.append(f"- `{o.trip_type}` {o.total_price} {o.currency} ({o.price_status}): "
                         f"{_segment_text(o)}")
    for err in report.errors:
        lines.append(f"- error: {err}")
    for warning in report.warnings[:6]:
        lines.append(f"- warning: {warning[:200]}")
    return lines + [""]


async def main() -> int:
    started = datetime.now(timezone.utc)
    out = ["# Probe: flights (w06)", "",
           f"Query: {ORIGIN} -> {DESTINATION}, {DEPART} / {RETURN}, 1 adult, economy. "
           f"Run at {started.isoformat()}.", "",
           "Prices are Google Flights metasearch observations (`observed_live`), never "
           "ticket guarantees. Baggage unknown unless stated. No fixture is relabelled.", ""]
    bd = BrightDataFlightsProvider(poll_interval=3.0)
    try:
        offers, report = await bd.search_round_trip(ORIGIN, DESTINATION, DEPART, RETURN)
    finally:
        await bd.client.aclose()
    out += _section(f"Bright Data Google Flights `{DATASET_ID}`", "live (attempted)", offers,
                    report, _save_raw("brightdata", offers, report) if offers else None)
    ff_offers, ff_report = await FastFlightsProvider().search_round_trip(
        ORIGIN, DESTINATION, DEPART, RETURN)
    out += _section("fast-flights (public Google Flights page)", "live (attempted)", ff_offers,
                    ff_report, _save_raw("fastflights", ff_offers, ff_report) if ff_offers else None)
    sp_offers, sp_report = await SerpApiFlightsProvider().search_round_trip(
        ORIGIN, DESTINATION, DEPART, RETURN)
    out += _section("SerpApi google_flights (no_cache=true)", "live (attempted)", sp_offers,
                    sp_report, _save_raw("serpapi", sp_offers, sp_report) if sp_offers else None)
    fixture = load_fixture_offers(explicit_opt_in=True)
    out += ["## Fixture `fixtures/flights.json`", "",
            "- mode: **fixture** (explicitly loaded by the probe; FICTIONAL carrier ZZ)",
            f"- offers: {len(fixture)}; price_status: "
            f"{sorted({o.price_status for o in fixture})}; evidence modes: "
            f"{sorted({e.source_mode for o in fixture for e in o.evidence})}", ""]
    live_ok = [name for name, rep, offs in (("brightdata", report, offers),
                                            ("fast-flights", ff_report, ff_offers),
                                            ("serpapi", sp_report, sp_offers)) if offs]
    out += ["## Verdict", "",
            f"- live sources with data: {', '.join(live_ok) or 'none'}",
            "- Bright Data decision rule: if `legs` and `pricing` come back empty from "
            "collect_by_url, fast-flights through the Bright Data SERP zone becomes primary "
            "(Bright Data as transport).", ""]
    REPORT.write_text("\n".join(out), encoding="utf-8")
    print(f"wrote {REPORT.relative_to(ROOT)}; live sources with data: {live_ok or 'none'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
