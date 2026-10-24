"""make probe-official: live collection of the GitHub Universe 2026 official catalog.

Writes probes/official.md. With --write-fixture (env OFFICIAL_WRITE_FIXTURE=1 also works,
since make passes no args) it also writes fixtures/official.json: a trimmed replay of the
same public capture, labelled source_mode="fixture". Nothing is written to the fixture when
the live run is not complete. No credentials are needed or stored.
"""

from __future__ import annotations

import asyncio
import collections
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from conferge.events.official.rainfocus import (  # noqa: E402
    API_BASE,
    CATALOG_URL,
    PORTAL_BASE,
    SPONSOR_URL,
    WORKFLOW_TOKEN,
)
from conferge.events.official.source import (  # noqa: E402
    FIXTURE_PATH,
    OfficialCollection,
    load_fixture,
    run,
)

REPORT_PATH = ROOT / "probes" / "official.md"
_SESSION_KEYS = ("sessionID", "code", "title", "abstract", "type", "status", "published")
_TIME_KEYS = ("sessionTimeID", "date", "endDate", "startTime", "endTime", "utcStartTime",
              "utcEndTime", "room", "capacity", "isHidden")
_PARTICIPANT_KEYS = ("speakerId", "fullName", "firstName", "lastName", "companyName",
                     "jobTitle", "roles", "bio", "linkedIn", "twitter", "published")
_SESSION_ATTRS = {"Topic", "Track", "GitHubproduct", "SessionTrackNotMulti", "SponsorSession"}
_EXHIBITOR_KEYS = ("exhibitorID", "name", "published", "status", "externalLink",
                   "linkedinLink", "description")
_EXHIBITOR_ATTRS = {"ExhibitorType", "Industry"}


_TRUNC = " [truncated in fixture]"


def _clip(value: Any, limit: int) -> Any:
    if isinstance(value, str) and len(value) > limit:
        return value[:limit].rstrip() + _TRUNC
    return value


def _attrs(item: dict[str, Any], keep: set[str]) -> list[dict[str, Any]]:
    return [{"attribute_id": a.get("attribute_id"), "value": a.get("value")}
            for a in item.get("attributevalues") or [] if a.get("attribute_id") in keep]


def trim_session(item: dict[str, Any]) -> dict[str, Any]:
    out = {k: item.get(k) for k in _SESSION_KEYS}
    out["abstract"] = _clip(out["abstract"], 500)
    out["times"] = [{k: t.get(k) for k in _TIME_KEYS if k in t} for t in item.get("times") or []]
    out["participants"] = [
        {k: (_clip(p.get(k), 240) if k == "bio" else p.get(k)) for k in _PARTICIPANT_KEYS
         if k in p}
        for p in item.get("participants") or []
    ]
    out["attributevalues"] = _attrs(item, _SESSION_ATTRS)
    return out


def trim_exhibitor(item: dict[str, Any]) -> dict[str, Any]:
    out = {k: item.get(k) for k in _EXHIBITOR_KEYS}
    out["description"] = _clip(out["description"], 300)
    out["booths"] = [{"booth": b.get("booth")} for b in item.get("booths") or []]
    out["attributevalues"] = _attrs(item, _EXHIBITOR_ATTRS)
    return out


def write_fixture(result: OfficialCollection) -> int:
    assert result.discovery is not None
    sessions = [trim_session(r.payload) for r in result.discovery.items
                if r.source_id.startswith("session:")]
    exhibitors = [trim_exhibitor(r.payload) for r in result.discovery.items
                  if r.source_id.startswith("exhibitor:")]
    doc = {
        "source_mode": "fixture",
        "label": "FIXTURE: trimmed replay of the public GitHub Universe 2026 RainFocus catalog. "
                 "Not live. Long abstracts/bios are clipped. Re-run make probe-official for live data.",
        "captured_from": "live",
        "captured_at": result.discovery.run_report.finished_at.isoformat(),
        "source_urls": [CATALOG_URL, SPONSOR_URL, f"{API_BASE}api/search"],
        "counts": {"sessions": len(sessions), "exhibitors": len(exhibitors)},
        "raw": {"sessions": sessions, "exhibitors": exhibitors},
    }
    FIXTURE_PATH.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")) + "\n",
                            encoding="utf-8")
    return FIXTURE_PATH.stat().st_size


def _table(counter: collections.Counter[Any]) -> list[str]:
    return [f"| {k} | {v} |" for k, v in counter.most_common()]


def render(result: OfficialCollection, *, mode_note: str, fixture_note: str | None) -> str:
    collected = result.events.collected_at.isoformat()
    lines = [
        "# Probe: official (GitHub Universe 2026)",
        "",
        f"- Probe run at: {datetime.now(timezone.utc).isoformat()}",
        f"- Data mode: **{result.source_mode}** ({mode_note})",
        f"- Status: **{result.status}**; collected_at: {collected}",
        "- Source: RainFocus public catalog behind the official attendee portal",
        f"  - portal: {PORTAL_BASE} (workflow `{WORKFLOW_TOKEN}`)",
        f"  - sessions page: {CATALOG_URL}",
        f"  - sponsors page: {SPONSOR_URL}",
        f"  - JSON API: POST {API_BASE}api/search (type=session|exhibitor, from=offset)",
        "  - widget id and api profile token are read at runtime from "
        "`flow/loadPage?pageUri=<page>&workflowApiToken=<workflow>` (not stored)",
        "- Bright Data: not needed (public JSON endpoint, no blocking observed). "
        "Unlocker remains the fallback if the portal starts blocking.",
        "",
    ]
    for report in result.events.reports:
        lines += [
            "## Run report",
            "",
            "| field | value |", "|---|---|",
            f"| status | {report.status} |",
            f"| termination | {report.termination} |",
            f"| source_mode | {report.source_mode} |",
            f"| pages | {report.pages} |",
            f"| fetched_count | {report.fetched_count} |",
            f"| unique_count | {report.unique_count} |",
            f"| expected_count (declared by source) | {report.expected_count} |",
            "",
        ]
        if report.errors:
            lines += ["Errors:", ""] + [f"- {e}" for e in report.errors] + [""]
        if report.warnings:
            lines += ["Report warnings:", ""] + [f"- {w}" for w in report.warnings] + [""]
    events, people, companies = result.events.items, result.people.items, result.companies.items
    lines += [
        "## Normalized output",
        "",
        f"- Events: {len(events)} (one per published time slot)",
        f"- People: {len(people)} (all from official catalog participant lists)",
        f"- Companies: {len(companies)} "
        f"({sum('sponsor' in c.categories for c in companies)} sponsors/exhibitors)",
        f"- Events with start_at: {sum(e.start_at is not None for e in events)}; "
        f"with speakers: {sum(bool(e.speaker_ids) for e in events)}; "
        f"with room: {sum(bool(e.room) for e in events)}",
        "",
        "| event_type, conference_relation | count |", "|---|---|",
        *_table(collections.Counter(f"{e.event_type}, {e.conference_relation}" for e in events)),
        "",
        "| person participation | count |", "|---|---|",
        *_table(collections.Counter(p.participation for p in people)),
        "",
        "| sponsor tier | count |", "|---|---|",
        *_table(collections.Counter(c for co in companies for c in co.categories
                                    if c.startswith("sponsor_tier:"))),
        "",
        "## Sample records",
        "",
    ]
    for event in sorted(events, key=lambda e: (e.start_at is None, e.start_at or 0))[:5]:
        lines.append(f"- `{event.id}` {event.title} | {event.start_at} | {event.room} | "
                     f"{event.conference_relation}")
    side = [e for e in events if e.conference_relation == "confirmed_side_event"][:3]
    for event in side:
        lines.append(f"- side event `{event.id}` {event.title} | {event.start_at} | "
                     f"{event.venue.name if event.venue else None}")
    lines += ["", "## Normalization warnings", ""]
    warn = collections.Counter(w.split(": ", 1)[-1].split(" [")[0][:60] for w in result.warnings)
    lines += [f"- {k} x{v}" for k, v in warn.most_common()] or ["- none"]
    lines += [
        "",
        "## Completeness notes",
        "",
        "- Times: explicit UTC from the catalog, local America/Los_Angeles derived; "
        "no time is invented.",
        "- `Social` items are sponsor or partner evening events listed by the organizer: "
        "`confirmed_side_event`, distinct from official sessions.",
        "- Speakers are `confirmed_speaker` only for the listed published sessions; "
        "this is not attendance evidence for anything else.",
        "- Prices, guest lists and attendance are not published by this source: null.",
        "- Venue coordinates are not published: coordinate_precision=unknown.",
        "",
    ]
    if fixture_note:
        lines += ["## Fixture", "", fixture_note, ""]
    return "\n".join(lines)


async def main() -> int:
    write = "--write-fixture" in sys.argv or os.getenv("OFFICIAL_WRITE_FIXTURE") == "1"
    result = await run()
    fixture_note = None
    mode_note = "live HTTP calls during this probe"
    if result.status == "failed" and FIXTURE_PATH.exists():
        print("live collection failed; reporting labelled fixture counts", file=sys.stderr)
        live_errors = result.events.errors
        result = load_fixture(explicit_opt_in=True)
        mode_note = f"FIXTURE shown because live failed: {live_errors}"
    elif write:
        if result.status == "ok":
            size = write_fixture(result)
            fixture_note = (f"fixtures/official.json rewritten from this live run "
                            f"({size} bytes), labelled source_mode=fixture.")
        else:
            fixture_note = "Live run incomplete: fixtures/official.json NOT rewritten."
    REPORT_PATH.parent.mkdir(exist_ok=True)
    REPORT_PATH.write_text(render(result, mode_note=mode_note, fixture_note=fixture_note),
                           encoding="utf-8")
    print(f"{result.source_mode} {result.status}: {len(result.events.items)} events, "
          f"{len(result.people.items)} people, {len(result.companies.items)} companies "
          f"-> {REPORT_PATH.relative_to(ROOT)}")
    return 0 if result.status != "failed" else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
