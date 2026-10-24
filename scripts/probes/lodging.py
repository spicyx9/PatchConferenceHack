"""Probe: lodging around Fort Mason, San Francisco, 2026-10-27 -> 2026-10-30, 1 adult, USD.

Writes probes/lodging.md. One real call per provider path:
- Booking search gd_m4bf7a917zfezv9d5 then detail gd_mdy9ld3p1e0oqlj9g4 (sb_price_type=total);
- Google Hotels gd_mg3gjfmg12tc2n5d4d (discover_by_search);
- Airbnb: pyairbnb (search_all + get_price + get_calendar), Bright Data gd_ld7ll037kqy322v05
  as fallback and also probed on its own.
No BRIGHTDATA_API_KEY -> those paths end with an explicit ``missing_credentials`` status.
pyairbnb is a pinned project dependency (``make install``).
Raw responses go to raw/lodging/ (gitignored). The labelled fixture is shown only as such.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from conferge.core.settings import env_value  # noqa: E402
from conferge.lodging import LodgingService, fixture_envelope  # noqa: E402
from conferge.lodging.airbnb import (  # noqa: E402
    AirbnbSource,
    BrightDataAirbnbBackend,
)
from conferge.lodging.booking import BookingSource  # noqa: E402
from conferge.lodging.google_hotels import GoogleHotelsSource  # noqa: E402
from conferge.lodging.models import LodgingQuery, Place  # noqa: E402

OUT = ROOT / "probes" / "lodging.md"
RAW = ROOT / "raw" / "lodging"
QUERY = LodgingQuery(
    check_in=date(2026, 10, 27), check_out=date(2026, 10, 30), adults=1, currency="USD",
    radius_km=3.0, limit=5, verify_top=5, conference_id="github-universe-2026",
    venues=[Place(id="venue:moscone-center", name="Moscone Center (not the venue, reference)",
                  lat=37.7842, lng=-122.4016)],
)


def _type(value: Any) -> str:
    return type(value).__name__ if value is not None else "null"


def _field_summary(row: dict[str, Any]) -> list[str]:
    lines = ["| field | type | example |", "|---|---|---|"]
    for key, value in row.items():
        example = json.dumps(value, default=str)[:90].replace("|", "/")
        lines.append(f"| `{key}` | {_type(value)} | {example} |")
    return lines


def _save_raw(name: str, records: list[Any]) -> str | None:
    if not records:
        return None
    RAW.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = RAW / f"{name}-{stamp}.json"
    path.write_text(json.dumps([r.model_dump(mode="json") for r in records], indent=1),
                    encoding="utf-8")
    return str(path.relative_to(ROOT))


async def _probe(name: str, src: Any) -> dict[str, Any]:
    started = datetime.now(timezone.utc)
    result = await src.search(QUERY)
    verify_report = None
    items = list(result.items)
    if items and hasattr(src, "verify"):
        items, verify_report = await src.verify(items, QUERY)
    return {"name": name, "result": result, "items": items, "verify": verify_report,
            "started": started, "raw": _save_raw(name, items)}


def _report_lines(p: dict[str, Any]) -> list[str]:
    rep = p["result"].run_report
    missing = any("missing_credentials" in e for e in rep.errors)
    state = "missing_credentials" if missing else f"{rep.status}/{rep.termination}"
    lines = [
        f"### {p['name']}", "",
        f"- **state: {state}** | source_mode: **{rep.source_mode}** | fetched {rep.fetched_count}"
        f" | unique {rep.unique_count} | pages {rep.pages} | expected {rep.expected_count}",
        f"- errors: {rep.errors or 'none'}",
        f"- warnings: {rep.warnings or 'none'}",
    ]
    if p["verify"] is not None:
        v = p["verify"]
        vmissing = any("missing_credentials" in e for e in v.errors)
        lines.append(f"- verification: {'missing_credentials' if vmissing else v.status + '/' + v.termination}"
                     f" | fetched {v.fetched_count} | errors {v.errors or 'none'}")
    if p["raw"]:
        lines.append(f"- raw saved (gitignored): `{p['raw']}`")
    if p["items"]:
        search = p["items"][0].payload.get("search")
        if isinstance(search, dict):
            lines += ["", f"Fields of the first raw row ({p['name']}, live):", "",
                      *_field_summary(search)]
    lines.append("")
    return lines


def _stay_table(stays: list[Any], distances: dict[str, list[dict[str, Any]]]) -> list[str]:
    lines = ["| provider | name | price_status | total | nightly_avg | taxes | fees | all fees? |"
             " availability | m to Fort Mason | walk min (est.) | mode | collected_at | link |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for s in stays:
        ev = s.evidence[0]
        walk = distances.get(s.id, [{}])[0].get("walk_minutes_estimate")
        lines.append(
            f"| {s.provider} | {s.name.replace('|', '/')[:48]} | {s.price_status} | "
            f"{s.total_price} {s.currency or ''} | {s.nightly_avg} | {s.taxes} | {s.fees_total} | "
            f"{s.includes_all_fees} | {s.availability} | {s.distance_to_venue_m} | {walk} | "
            f"{ev.source_mode} | {ev.collected_at.isoformat() if ev.collected_at else 'null'} | "
            f"{s.booking_url or 'null'} |")
    return lines


async def main() -> int:
    run_at = datetime.now(timezone.utc)
    sources = {
        "booking": BookingSource(),
        "google_hotels": GoogleHotelsSource(),
        "airbnb": AirbnbSource(),
        "airbnb_brightdata_only": AirbnbSource(primary=BrightDataAirbnbBackend(),
                                               fallback=None),
    }
    try:
        probes = await asyncio.gather(*(_probe(n, s) for n, s in sources.items()))
    finally:
        for s in sources.values():
            await s.aclose()
    service = LodgingService(sources={})
    records = [r for p in probes if p["name"] != "airbnb_brightdata_only" for r in p["items"]]
    reports = [p["result"].run_report for p in probes if p["name"] != "airbnb_brightdata_only"]
    verifies = [p["verify"] for p in probes
                if p["verify"] is not None and p["name"] != "airbnb_brightdata_only"]
    search = service.assemble(records, QUERY, reports, verifies)
    env = search.envelope
    has_pyairbnb = importlib.util.find_spec("pyairbnb") is not None
    lines = [
        "# Probe: lodging (window 05)", "",
        f"- run at: {run_at.isoformat()}",
        "- query: Fort Mason Center (37.8060, -122.4320), radius 3 km, check-in 2026-10-27, "
        "check-out 2026-10-30 (3 nights), 1 adult, 1 room, USD, country us, limit 5 per input",
        f"- BRIGHTDATA_API_KEY present: {bool(env_value('BRIGHTDATA_API_KEY'))} | "
        f"pyairbnb importable: {has_pyairbnb}",
        f"- envelope: **source_mode {env.source_mode}**, status **{env.status}**, "
        f"{len(env.items)} stays, {len(search.groups)} cross-provider dedup groups",
        "- price_status counts: " + ", ".join(
            f"{k} {sum(1 for s in env.items if s.price_status == k)}"
            for k in ("verified_bookable", "quoted_total", "indicative", "unknown", "unavailable")),
        "- rule: `verified_bookable` only with a dated detail re-check < 30 min, verified "
        "availability, all-fees total and deeplink; Airbnb and Google Hotels never reach it "
        "(taxes not exposed / metasearch).", "",
        "## Providers", "",
    ]
    for p in probes:
        lines += _report_lines(p)
    lines += ["## Normalized stays (live)", ""]
    if env.items:
        lines += _stay_table(env.items, search.distances)
    else:
        lines.append("No live stay normalized.")
    if search.warnings:
        lines += ["", "Normalization warnings:", "", *[f"- {w}" for w in search.warnings[:30]]]
    try:
        fx = fixture_envelope(explicit_opt_in=True)
        lines += ["", "## FIXTURE (labelled, not live): fixtures/lodging.json", "",
                  f"- {len(fx.items)} stays, source_mode **{fx.source_mode}**; Booking and Google "
                  "Hotels rows are fictional (no key), Airbnb rows are a trimmed real pyairbnb "
                  "capture, all marked fixture.", ""]
        lines += _stay_table(fx.items, {})
    except Exception as exc:  # noqa: BLE001 - probe reports, never crashes
        lines += ["", f"Fixture could not be loaded: {type(exc).__name__}: {exc}"]
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}: {len(env.items)} live stays, status {env.status}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
