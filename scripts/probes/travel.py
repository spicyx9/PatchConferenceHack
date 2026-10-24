"""Probe for window 11 (ground travel): `make probe-travel` writes probes/travel.md.

Live calls: api.bart.gov (public key), router.project-osrm.org (drive),
routing.openstreetmap.de (foot), Uber estimator via Bright Data Web Unlocker if configured.
Set TRAVEL_WRITE_FIXTURE=1 to also write fixtures/travel.json, a relabelled replay.
The probe departure time is an input parameter, not a claimed flight arrival.
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from conferge.travel.fixture import FIXTURE_PATH, relabel_as_fixture
from conferge.travel.models import RoutePlan, utcnow
from conferge.travel.places import EMBARCADERO, FORT_MASON, OAK, SF_TIMEZONE, SFO, SJC
from conferge.travel.routes import default_planner

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "probes" / "travel.md"
DEPART = datetime(2026, 10, 27, 18, 0, tzinfo=ZoneInfo(SF_TIMEZONE))


def _fmt(value: datetime | None) -> str:
    return value.strftime("%Y-%m-%d %H:%M %z") if value else "null"


def render(plans: list[RoutePlan], started: datetime) -> str:
    lines = [
        "# Probe: travel (window 11)", "",
        f"- collected_at: {utcnow().isoformat()} (started {started.isoformat()})",
        f"- probe departure input: {DEPART.isoformat()} ({SF_TIMEZONE}); not a flight time",
        "- data: live calls only; nothing in this report is fixture", "",
    ]
    for plan in plans:
        lines += [f"## {plan.origin.name} -> {plan.destination.name}", "",
                  f"status **{plan.status}**, source_mode `{plan.source_mode}`, "
                  f"options {len(plan.options)}", ""]
        for r in plan.reports:
            lines.append(f"- report `{r.provider}`: {r.status}/{r.termination}, "
                         f"fetched {r.fetched_count}, unique {r.unique_count}"
                         + (f", errors: {'; '.join(r.errors)}" if r.errors else "")
                         + (f", warnings: {'; '.join(r.warnings)}" if r.warnings else ""))
        for e in plan.errors:
            lines.append(f"- note: {e}")
        lines.append("")
        if plan.options:
            lines += ["| option | leg | mode | depart | arrive | min (status) | price (status) "
                      "| provider | source_mode | source |", "|---|---|---|---|---|---|---|---|---|---|"]
        for opt in plan.options:
            for i, leg in enumerate(opt.legs):
                price = f"{leg.price.amount} {leg.price.currency}" if leg.price.amount else "null"
                lines.append(
                    f"| {opt.label} | {i + 1} {leg.from_place.id} -> {leg.to_place.id} "
                    f"| {leg.mode}{' ' + leg.line if leg.line else ''} "
                    f"| {_fmt(leg.departure_local)} | {_fmt(leg.arrival_local)} "
                    f"| {leg.duration_minutes} ({leg.duration_status}) "
                    f"| {price} ({leg.price.status}) | {leg.provider} | {leg.source_mode} "
                    f"| {leg.source_url or 'null'} |")
            total = opt.total_price
            amount = f"{total.amount} {total.currency}" if total.amount else "null"
            lines.append(f"| **{opt.label} total** | | | | | {opt.total_duration_minutes} "
                         f"| {amount} ({total.status}) "
                         f"| complete={opt.complete} | | |")
        lines.append("")
    return "\n".join(lines) + "\n"


async def main() -> None:
    started = utcnow()
    planner = default_planner()
    try:
        plans = [await planner.plan(a, FORT_MASON, depart_at=DEPART) for a in (SFO, OAK, SJC)]
        plans.append(await planner.plan(FORT_MASON, EMBARCADERO, depart_at=DEPART))
    finally:
        await planner.aclose()
    OUT.write_text(render(plans, started), encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}")
    for p in plans:
        print(f"{p.origin.id} -> {p.destination.id}: {p.status}, {len(p.options)} options")
    if os.getenv("TRAVEL_WRITE_FIXTURE") == "1":
        data = {
            "source_mode": "fixture",
            "note": "Replay of a live probe capture, relabelled fixture. Not live data.",
            "captured_live_at": started.isoformat(),
            "plans": [relabel_as_fixture(p) for p in plans],
        }
        FIXTURE_PATH.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n",
                                encoding="utf-8")
        print(f"wrote {FIXTURE_PATH.relative_to(ROOT)}")


if __name__ == "__main__":
    asyncio.run(main())
