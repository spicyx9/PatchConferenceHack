"""Probe: Partiful public Explore SF, 2026-10-27..30.

Writes probes/partiful.md. `--refresh-fixture` rewrites fixtures/partiful.json from the
live run (sanitized: event subset only, no guests, no owner ids).
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
from conferge.events.partiful import PartifulSource, load_fixture, normalize  # noqa: E402

OUT = ROOT / "probes" / "partiful.md"
FIXTURE = ROOT / "fixtures" / "partiful.json"
WINDOW = DiscoveryQuery(
    domain="events", conference_id="github-universe-2026", city="San Francisco",
    start_date=date(2026, 10, 27), end_date=date(2026, 10, 30), limit=1000,
    filters={"region": "sf"},
)
_KEEP = ("id", "title", "description", "startDate", "endDate", "timezone", "locationInfo",
         "status", "isPublic", "goingGuestCount", "interestedGuestCount", "showGuestCount",
         "hostName")


def _sanitize(payload: dict) -> dict:
    event = payload.get("event") or {}
    return {"event": {k: event.get(k) for k in _KEEP if k in event},
            "explore_group": payload.get("explore_group")}


async def main() -> int:
    refresh = "--refresh-fixture" in sys.argv
    src = PartifulSource()
    try:
        everything = await src.discover(WINDOW.model_copy(update={"start_date": None, "end_date": None}))
        result = await src.discover(WINDOW)
    finally:
        await src.aclose()
    rep = result.run_report
    lines = [
        "# Probe — Partiful (window 01)", "",
        f"- run at: {datetime.now(timezone.utc).isoformat()}",
        "- endpoints: `GET https://partiful.com/explore/sf` (buildId) then "
        "`GET https://partiful.com/_next/data/<buildId>/explore/sf.json`",
        f"- **source_mode: {rep.source_mode}** | status: **{rep.status}** | "
        f"termination: **{rep.termination}**",
        f"- raw items: {rep.fetched_count} | unique event.id: {rep.unique_count} | "
        f"in 2026-10-27..30: {len(result.items)} | declared total (regionEventCounts.SF): "
        f"{rep.expected_count}",
        f"- warnings: {rep.warnings or 'none'}",
        f"- errors: {rep.errors or 'none'}",
        "- completeness: **not claimed** — Explore is a curated page, not a catalogue.", "",
    ]
    events = [normalize(r) for r in result.items]
    if events:
        lines += ["## Events in window (live)", "", "| start (local) | title | going | url |",
                  "|---|---|---|---|"]
        for ev in sorted(events, key=lambda e: e.start_at or datetime.max.replace(tzinfo=timezone.utc)):
            lines.append(f"| {ev.start_at.isoformat() if ev.start_at else 'null'} | "
                         f"{ev.title.replace('|', '/')[:70]} | {ev.registered_count} | {ev.source_url} |")
        lines.append("")
    elif rep.status == "failed":
        fx = load_fixture(FIXTURE, explicit_opt_in=True)
        lines += ["## Live failed — FIXTURE shown (not live)", "",
                  f"- {fx.run_report.warnings[0]}; {len(fx.items)} records", ""]
    else:
        lines += ["## No live Explore item falls in 2026-10-27..30", ""]
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines[:9]))

    if refresh and everything.items:
        in_window = {r.source_id for r in result.items}
        ordered = sorted(everything.items, key=lambda r: (r.source_id not in in_window,
                                                          r.payload["event"].get("startDate") or ""))
        entries = [_sanitize(r.payload) for r in ordered][:6]
        FIXTURE.write_text(json.dumps({
            "source_mode": "fixture",
            "provider": "partiful",
            "captured_at": max(r.collected_at for r in everything.items).isoformat(),
            "note": "Captured from live public Partiful Explore SF by scripts/probes/partiful.py "
                    "--refresh-fixture, sanitized (no guests, no owner ids). Events in the Oct "
                    "27-30 window first, then earliest others. FIXTURE: not a live response.",
            "entries": entries,
        }, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"fixture rewritten: {len(entries)} entries")
    return 0 if rep.status != "failed" else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
