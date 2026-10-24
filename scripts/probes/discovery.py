"""Window 04 probe: SERP discovery, routing, live detail verification, Facebook events.

Writes probes/discovery.md. Every block states its mode:
1. live SERP through BrightDataClient.serp (fails visibly without a key);
2. explicit fixture candidates (synthetic SERP replay) only when live SERP failed;
3. live verification of those candidate URLs through the router (public pages);
4. live Facebook Events dataset attempt.

Usage: uv run python scripts/run_probe.py discovery [--no-details]
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from conferge.core.brightdata import BrightDataClient  # noqa: E402
from conferge.core.schemas import Conference, DiscoveryQuery, RunReport  # noqa: E402
from conferge.events.discovery import (  # noqa: E402
    FacebookEventsSource,
    SerpDiscoverySource,
    build_queries,
    fixture_plan,
    load_fixture,
    run,
)

OUT = ROOT / "probes" / "discovery.md"
CONFERENCE = Conference(
    id="github-universe-2026", name="GitHub Universe", start_date=date(2026, 10, 28),
    end_date=date(2026, 10, 29), city="San Francisco", venue_name="Fort Mason Center",
    timezone="America/Los_Angeles", latitude=37.8060, longitude=-122.4320,
    topics=["AI agents", "developer tools", "Copilot", "MCP"],
)


def _sponsor_names() -> list[str]:
    """Exhibitor names from window 03's labelled fixture (read-only), if present."""
    path = ROOT / "fixtures" / "official.json"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return sorted({e["name"] for e in raw["raw"]["exhibitors"] if e.get("name")})
    except (OSError, KeyError, TypeError, ValueError):
        return []


def _report_line(r: RunReport) -> str:
    return (f"`{r.provider}` status=**{r.status}** termination=`{r.termination}` "
            f"mode=`{r.source_mode}` fetched={r.fetched_count} unique={r.unique_count} "
            f"pages={r.pages}")


def _cell(value: object) -> str:
    return str(value if value is not None else "null").replace("|", "/").replace("\n", " ")


async def main(details: bool = True) -> int:
    started = datetime.now(timezone.utc)
    bd = BrightDataClient.from_env()
    lines: list[str] = [
        "# Probe: discovery (window 04)", "",
        f"- collected_at: {started.isoformat()}",
        "- anchor: GitHub Universe 2026, Fort Mason Center, San Francisco, 2026-10-28..29",
        "- rule: a SERP hit is a candidate URL, never a confirmed event; Events come only "
        "from fetched detail pages and are linked at most as `candidate`.", "",
    ]
    plan = fixture_plan(explicit_opt_in=True)  # the plan itself is configuration, not data
    queries = build_queries(plan)
    lines += [f"## Query plan ({len(queries)} queries)", "",
              "| family | query | reason |", "|---|---|---|"]
    lines += [f"| {q.family} | `{_cell(q.text)}` | {_cell(q.reason)} |" for q in queries]
    lines.append("")

    # 1. live SERP
    async with bd:
        live = await SerpDiscoverySource(bd).discover_plan(plan)
    lines += ["## 1. Live SERP (Bright Data)", "", "- " + _report_line(live.run_report)]
    lines += [f"- error: {e}" for e in live.errors]
    lines.append("")

    discovery = live
    if live.run_report.status == "failed":
        discovery = await load_fixture(explicit_opt_in=True)
        lines += [
            "## 2. Candidates: FIXTURE (live SERP failed)", "",
            "Explicit fixture `fixtures/discovery.json`: synthetic SERP replay built from real "
            "URLs captured live by w01/w02. Query to URL pairing is constructed, not observed.",
            "", "- " + _report_line(discovery.run_report), "",
        ]
    else:
        lines += ["## 2. Candidates: LIVE", "", "- " + _report_line(live.run_report), ""]
    lines += ["| conf. | platform | adapter | kind | canonical URL | first query | mode |",
              "|---|---|---|---|---|---|---|"]
    for item in discovery.items:
        p = item.payload
        lines.append(
            f"| {p['confidence']} | {p['route']['platform']} | {p['route']['adapter']} | "
            f"{p['route']['page_kind']} | {_cell(p['canonical_url'])} | "
            f"`{_cell(p['discovered_by'][0]['query'])}` | {item.source_mode} |"
        )
    lines.append("")

    # 3. live verification of candidates through the router
    if details:
        detail_bd = BrightDataClient.from_env()
        async with detail_bd:
            source = SerpDiscoverySource(detail_bd)
            result = await run(CONFERENCE, source=source, plan=plan, discovery=discovery,
                               sponsor_names=_sponsor_names(), aliases=["Universe"])
        env = result.events
        lines += ["## 3. Detail verification (LIVE public pages via router)", "",
                  f"- envelope: mode=`{env.source_mode}` status=**{env.status}** "
                  f"events={len(env.items)}"]
        lines += ["- " + _report_line(r) for r in env.reports]
        lines += ["", "| candidate URL | adapter | outcome | detail provider | note |",
                  "|---|---|---|---|---|"]
        for o in result.outcomes:
            lines.append(f"| {_cell(o.url)} | {o.adapter} | **{o.status}** | "
                         f"{_cell(o.detail_provider)} | {_cell(o.error)} |")
        lines += ["", "### Events (normalized from detail pages)", "",
                  "| title | start | venue | relation | score | mode | source |",
                  "|---|---|---|---|---|---|---|"]
        for ev in env.items:
            mode = ev.evidence[0].source_mode if ev.evidence else "?"
            venue = ev.venue.name or ev.venue.address if ev.venue else None
            lines.append(
                f"| {_cell(ev.title)} | {_cell(ev.start_at.isoformat() if ev.start_at else None)}"
                f" | {_cell(venue)} | {ev.conference_relation} | {_cell(ev.relation_score)} | "
                f"{mode} | {_cell(ev.source_url)} |"
            )
        lines += ["", "### Dedup groups", ""]
        lines += [f"- {g['canonical_id']}: {g['decision']} ({g['merge_confidence']}) "
                  f"{'; '.join(g['reasons'])}" for g in result.groups]
        lines.append("")

    # 4. Facebook Events dataset
    fb_bd = BrightDataClient.from_env()
    async with fb_bd:
        fb = await FacebookEventsSource(fb_bd).discover(DiscoveryQuery(
            domain="events", city="San Francisco", start_date=date(2026, 10, 26),
            end_date=date(2026, 10, 31), limit=50,
        ))
    lines += ["## 4. Facebook Events (Bright Data dataset gd_m14sd0to1jz48ppm51)", "",
              "- " + _report_line(fb.run_report)]
    lines += [f"- error: {e}" for e in fb.errors]
    lines += ["", "No fixture substituted for Facebook: a failed run stays failed.", ""]

    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}")
    print("\n".join(lines[:4]))
    return 0


if __name__ == "__main__":
    asyncio.run(main(details="--no-details" not in sys.argv))
