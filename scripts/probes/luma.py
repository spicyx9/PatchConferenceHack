"""Probe: Luma public discovery around Fort Mason, SF, 2026-10-27..30.

Writes probes/luma.md. `--refresh-fixture` rewrites fixtures/luma.json from the live
run (sanitized: no featured guests, hosts reduced to public name + id).
Live failure is reported as such; the fixture is only shown, labelled, as a fallback.
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from conferge.core.schemas import DiscoveryQuery  # noqa: E402
from conferge.events.luma import LumaSource, load_fixture, normalize  # noqa: E402

OUT = ROOT / "probes" / "luma.md"
FIXTURE = ROOT / "fixtures" / "luma.json"
QUERY = DiscoveryQuery(
    domain="events", conference_id="github-universe-2026", city="San Francisco",
    latitude=37.8060, longitude=-122.4320, radius_km=15,
    start_date=date(2026, 10, 27), end_date=date(2026, 10, 30), limit=1000,
)


def _sanitize(entry: dict) -> dict:
    event = dict(entry.get("event") or {})
    event.pop("virtual_info", None)
    cal = entry.get("calendar") or {}
    return {
        "api_id": entry.get("api_id"),
        "event": event,
        "calendar": {k: cal.get(k) for k in ("api_id", "name", "slug", "is_personal")},
        "start_at": entry.get("start_at"),
        "hosts": [{"api_id": h.get("api_id"), "name": h.get("name")}
                  for h in entry.get("hosts") or []],
        "guest_count": entry.get("guest_count"),
        "ticket_count": entry.get("ticket_count"),
        "ticket_info": entry.get("ticket_info"),
        "registration_availability": entry.get("registration_availability"),
    }


async def main() -> int:
    refresh = "--refresh-fixture" in sys.argv
    src = LumaSource()
    try:
        result = await src.discover(QUERY)
    finally:
        await src.aclose()
    rep = result.run_report
    lines = [
        "# Probe — Luma (window 01)", "",
        f"- run at: {datetime.now(timezone.utc).isoformat()}",
        "- endpoint: `GET https://api2.luma.com/discover/get-paginated-events` "
        "(lat 37.8060, lon -122.4320, pagination_limit 50, pagination_cursor)",
        "- query: SF, 2026-10-27..2026-10-30 (local date), radius 15 km of Fort Mason",
        f"- **source_mode: {rep.source_mode}** | status: **{rep.status}** | "
        f"termination: **{rep.termination}**",
        f"- pages: {rep.pages} | raw rows: {rep.fetched_count} | unique api_id: "
        f"{rep.unique_count} | kept after filters: {len(result.items)} | expected_count: "
        f"{rep.expected_count} (Luma exposes no total)",
        f"- warnings: {rep.warnings or 'none'}",
        f"- errors: {rep.errors or 'none'}", "",
    ]
    events = [normalize(r) for r in result.items]
    if events:
        lines += ["## Events in window (live)", "", "| start (local) | title | venue precision | "
                  "free | registered | url |", "|---|---|---|---|---|---|"]
        for ev in sorted(events, key=lambda e: e.start_at or datetime.max.replace(tzinfo=timezone.utc)):
            title = ev.title.replace("|", "/")[:70]
            prec = ev.venue.coordinate_precision if ev.venue else "none"
            lines.append(f"| {ev.start_at.isoformat() if ev.start_at else 'null'} | {title} | "
                         f"{prec} | {ev.is_free} | {ev.registered_count} | {ev.source_url} |")
        lines.append("")
    else:
        fx = load_fixture(FIXTURE, explicit_opt_in=True)
        lines += ["## Live returned nothing in window — FIXTURE shown (not live)", "",
                  f"- {fx.run_report.warnings[0]}; {len(fx.items)} records", ""]
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines[:10]))

    if refresh and result.items:
        by_day: dict[str, list] = {}
        for ev, rec in zip(events, result.items, strict=True):
            by_day.setdefault(ev.start_at.date().isoformat() if ev.start_at else "", []).append(rec)
        picked: list = []
        while len(picked) < 12 and any(by_day.values()):  # round-robin over local days
            for day in sorted(by_day):
                if by_day[day] and len(picked) < 12:
                    picked.append(by_day[day].pop(0))
        entries = [_sanitize(r.payload) for r in picked]
        FIXTURE.write_text(json.dumps({
            "source_mode": "fixture",
            "provider": "luma",
            "captured_at": max(r.collected_at for r in result.items).isoformat(),
            "note": "Captured from the live public Luma discover feed by scripts/probes/luma.py "
                    "--refresh-fixture, then sanitized (no featured guests, hosts = public "
                    "name + id). FIXTURE: not a live response.",
            "query": QUERY.model_dump(mode="json"),
            "entries": entries,
        }, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"fixture rewritten: {len(entries)} entries")
    return 0 if rep.status != "failed" else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
