"""Probe for window 02: Eventbrite search + conference-party aggregators.

Run: make probe-eventbrite-aggregators
Writes probes/eventbrite-aggregators.md with live status, raw/unique counts,
termination and every incomplete-window reason. When a live source fails, the
fixture counts are shown in a separate section labelled FIXTURE.
Set W02_WRITE_FIXTURE=1 to rebuild fixtures/eventbrite-aggregators.json from
this live run (records relabelled source_mode=fixture, original collected_at kept).
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from conferge.core.schemas import DiscoveryQuery, DiscoveryResult, SourceRecord  # noqa: E402
from conferge.events.aggregators.normalize import normalize_records as norm_agg  # noqa: E402
from conferge.events.aggregators.source import AggregatorSource  # noqa: E402
from conferge.events.aggregators.source import load_fixture_records as agg_fixture  # noqa: E402
from conferge.events.eventbrite.normalize import normalize_records as norm_eb  # noqa: E402
from conferge.events.eventbrite.source import (  # noqa: E402
    EXPANSIONS,
    PAGE_SIZE,
    SEARCH_PATH,
    EventbriteSource,
)
from conferge.events.eventbrite.source import load_fixture_records as eb_fixture  # noqa: E402

REPORT = ROOT / "probes" / "eventbrite-aggregators.md"
FIXTURE = ROOT / "fixtures" / "eventbrite-aggregators.json"
CONFERENCE_ID = "github-universe-2026"
WINDOW = (date(2026, 10, 27), date(2026, 10, 30))

AGGREGATOR_TARGETS = [
    ("conferenceparties", "github26", "GitHub Universe 2026 (anchor)"),
    ("conferenceparties", "reinvent2026", "AWS re:Invent 2026 (parser breadth)"),
]
_TRIM_KEYS = {"debug_info", "urgency_signals", "locations", "dedup", "image_id", "saves"}


async def probe_eventbrite(keywords: list[str]) -> tuple[DiscoveryResult, DiscoveryQuery]:
    query = DiscoveryQuery(
        domain="events", city="San Francisco", start_date=WINDOW[0], end_date=WINDOW[1],
        keywords=keywords, limit=1000,
    )
    return await EventbriteSource().discover(query), query


async def probe_aggregators() -> list[tuple[str, str, str, DiscoveryResult]]:
    query = DiscoveryQuery(domain="events", conference_id=CONFERENCE_ID, limit=1000)
    results = await asyncio.gather(*(
        AggregatorSource(site, slug).discover(query)  # type: ignore[arg-type]
        for site, slug, _ in AGGREGATOR_TARGETS
    ))
    return [(s, slug, note, r) for (s, slug, note), r in zip(AGGREGATOR_TARGETS, results, strict=True)]


def _cell(value: Any) -> str:
    return str(value).replace("|", "/").replace("\n", " ") if value not in (None, "") else "null"


def _report_row(name: str, note: str, result: DiscoveryResult) -> str:
    r = result.run_report
    return (
        f"| {name} | {note} | {r.source_mode} | {r.status} | {r.termination} | "
        f"{r.fetched_count} | {r.unique_count} | {r.pages} | {_cell(r.expected_count)} |"
    )


def _issues(name: str, result: DiscoveryResult) -> list[str]:
    r = result.run_report
    lines = [f"- `{name}` error: {e}" for e in r.errors]
    lines += [f"- `{name}` warning: {w}" for w in r.warnings[:15]]
    if len(r.warnings) > 15:
        lines.append(f"- `{name}`: {len(r.warnings) - 15} more warnings")
    return lines


def _samples(events: list[Any], limit: int = 5) -> list[str]:
    lines = []
    for event in events[:limit]:
        venue = event.venue.name if event.venue and event.venue.name else None
        lines.append(
            f"| {_cell(event.title)} | {_cell(event.start_at and event.start_at.isoformat())} | "
            f"{_cell(venue)} | {_cell(', '.join(event.organizer_names))} | "
            f"{_cell(event.registration_url)} | {event.evidence[0].source_mode} |"
        )
    return lines


def _fixture_record(record: SourceRecord) -> dict[str, Any]:
    payload = {k: v for k, v in record.payload.items() if k not in _TRIM_KEYS}
    data = record.model_copy(update={"source_mode": "fixture", "payload": payload})
    return json.loads(data.model_dump_json())


def write_fixture(eb_items: list[SourceRecord], agg: dict[str, list[SourceRecord]]) -> None:
    aggregators = agg.get("conferenceparties:github26", []) + agg.get(
        "conferenceparties:reinvent2026", []
    )[: max(0, 20 - len(agg.get("conferenceparties:github26", [])))]
    data = {
        "source_mode": "fixture",
        "description": (
            "Real public records captured live by scripts/probes/eventbrite-aggregators.py, "
            "relabelled source_mode=fixture. collected_at is the original capture time. "
            "Not live data; display data_mode=fixture when used."
        ),
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "eventbrite": [_fixture_record(r) for r in eb_items[:8]],
        "aggregators": [_fixture_record(r) for r in aggregators],
    }
    FIXTURE.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


async def main() -> int:
    collected = datetime.now(timezone.utc)
    (eb_all, eb_query), (eb_ai, _) = await asyncio.gather(
        probe_eventbrite([]), probe_eventbrite(["AI"])
    )
    aggregator_results = await probe_aggregators()

    lines = [
        "# Probe: eventbrite-aggregators (window 02)",
        "",
        f"- Run at: {collected.isoformat()}",
        "- Command: `make probe-eventbrite-aggregators`",
        f"- Anchor: GitHub Universe 2026 (`{CONFERENCE_ID}`), San Francisco, "
        f"window {WINDOW[0]}..{WINDOW[1]}",
        "- Every row below is `live` unless explicitly labelled FIXTURE.",
        "",
        "## Run reports",
        "",
        "| Source | Target | Mode | Status | Termination | Raw | Unique | Pages | Declared |",
        "|---|---|---|---|---|---|---|---|---|",
        _report_row("eventbrite", f"SF {WINDOW[0]}..{WINDOW[1]}, all events", eb_all),
        _report_row("eventbrite", f"SF {WINDOW[0]}..{WINDOW[1]}, q=AI", eb_ai),
    ]
    agg_records: dict[str, list[SourceRecord]] = {}
    for site, slug, note, result in aggregator_results:
        lines.append(_report_row(f"{site}/{slug}", note, result))
        agg_records[f"{site}:{slug}"] = result.items
    lines += ["", "## Incomplete-window reasons, warnings and errors", ""]
    issues = _issues("eventbrite all", eb_all) + _issues("eventbrite q=AI", eb_ai)
    for site, slug, _, result in aggregator_results:
        issues += _issues(f"{site}/{slug}", result)
    lines += issues or ["- none"]

    eb_events, eb_errors = norm_eb(eb_ai.items or eb_all.items)
    anchor = agg_records.get("conferenceparties:github26", [])
    agg_events, agg_errors = norm_agg(anchor, conference_id=CONFERENCE_ID)
    lines += [
        "",
        "## Sample normalized events",
        "",
        "### conferenceparties.com/github26 (GitHub Universe side events, relation=candidate)",
        "",
        "| Title | Start | Venue | Hosts | RSVP | Mode |",
        "|---|---|---|---|---|---|",
        *(_samples(agg_events, 10) or ["| none | | | | | |"]),
        "",
        "### Eventbrite SF, q=AI",
        "",
        "| Title | Start | Venue | Organizer | URL | Mode |",
        "|---|---|---|---|---|---|",
        *(_samples(eb_events) or ["| none | | | | | |"]),
        "",
        f"Normalization errors: {len(eb_errors) + len(agg_errors)}",
        *[f"- {e}" for e in (eb_errors + agg_errors)[:10]],
        "",
        "## Eventbrite request actually sent",
        "",
        "1. `GET https://www.eventbrite.com/d/ca--san-francisco/events/` (browser User-Agent)"
        " sets cookie `csrftoken`; `placeId` read from `window.__SERVER_DATA__`.",
        f"2. `POST https://www.eventbrite.com{SEARCH_PATH}` with header `X-CSRFToken` and body:",
        "",
        "```json",
        json.dumps({
            "event_search": {
                "places": ["85922583"], "page": 1, "page_size": PAGE_SIZE,
                "online_events_only": False,
                "date_range": {"from": str(WINDOW[0]), "to": str(WINDOW[1])},
                "q": "AI",
            },
            "expand.destination_event": EXPANSIONS,
        }, indent=1),
        "```",
        "",
        "`\"dates\": \"custom\"` (older clients) is rejected with ARGUMENTS_ERROR;"
        " `date_range` alone is accepted. page_count stops at 19 (950 rows): ranges whose"
        " declared total exceeds 900 are split by date; a single day above the cap is"
        " reported `page_cap`.",
    ]

    failed = [name for name, res in [("eventbrite", eb_all)] if res.run_report.status == "failed"]
    failed += [f"{s}/{g}" for s, g, _, r in aggregator_results
               if r.run_report.status == "failed" and g != "reinvent2026"]
    if failed and FIXTURE.exists():
        eb_fix = eb_fixture(explicit_opt_in=True)
        agg_fix = agg_fixture(explicit_opt_in=True)
        lines += [
            "",
            "## FIXTURE (shown because a live source failed: " + ", ".join(failed) + ")",
            "",
            f"- fixtures/eventbrite-aggregators.json: {len(eb_fix)} Eventbrite records, "
            f"{len(agg_fix)} aggregator records, all `source_mode=fixture`.",
        ]

    if os.getenv("W02_WRITE_FIXTURE") == "1":
        write_fixture(eb_ai.items or eb_all.items, agg_records)
        lines += ["", f"Fixture rebuilt from this live run: `{FIXTURE.relative_to(ROOT)}`."]

    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {REPORT.relative_to(ROOT)}")
    for line in lines[8:20]:
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
