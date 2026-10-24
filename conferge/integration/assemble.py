"""Merge source slices into one dataset and into the ``DemoData`` the API accepts.

Domains with no merged source window (lodging w05, flights w06) come from the
window 12 fixture and keep ``source_mode=fixture`` with a warning naming the
missing window. The anchor conference comes from the official source when it
produced one; otherwise from the API fixture, labelled as such.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from conferge.api.data import DemoData, DomainSlice
from conferge.api.data import load_fixture as load_api_fixture
from conferge.core.schemas import Company, Conference, Event, Person, RunStatus
from conferge.integration.sources import SourceSlice

_RANK: dict[str, int] = {"ok": 0, "degraded": 1, "failed": 2}


@dataclass
class Assembly:
    conference: Conference
    conference_origin: str
    events: list[Event]
    people: list[Person]
    companies: list[Company]
    slices: list[SourceSlice]
    demo: DemoData
    duplicates: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def data_mode(self) -> str:
        modes = {s.source_mode for s in self.slices if s.count}
        return modes.pop() if len(modes) == 1 else ("mixed" if modes else "fixture")


def _worst(statuses: list[str]) -> RunStatus:
    return max(statuses, key=lambda s: _RANK[s], default="failed")  # type: ignore[return-value]


def _domain(slices: list[SourceSlice], attr: str, fallback: datetime) -> DomainSlice:
    used = [s for s in slices if getattr(s, attr)]
    if not used:
        return DomainSlice("fixture", "failed", fallback,
                           [f"no merged source produced {attr}"])
    modes = {s.source_mode for s in used}
    mode = modes.pop() if len(modes) == 1 else "mixed"
    warnings = [f"{s.name}: {s.source_mode} {s.status}" for s in used]
    warnings += [f"{s.name}: {w}" for s in used for w in s.warnings[:3]]
    collected = max((s.collected_at for s in used if s.collected_at), default=fallback)
    return DomainSlice(mode, _worst([s.status for s in used]), collected, warnings)


def _dedup(items: list[Any], seen_ids: set[str], seen_urls: dict[str, str],
           duplicates: list[str], listing_urls: set[str] | None = None) -> list[Any]:
    out = []
    for item in items:
        if item.id in seen_ids:
            duplicates.append(f"duplicate id {item.id}")
            continue
        url = str(getattr(item, "source_url", None) or "")
        if listing_urls and url in listing_urls:
            url = ""  # a catalog URL shared by many records is not an identity
        if url and url in seen_urls:
            # Same event page across sources: keep the first record, never force
            # a merge of fields; the duplicate is listed so the report shows it.
            duplicates.append(f"{item.id} same source_url as {seen_urls[url]}")
            continue
        seen_ids.add(item.id)
        if url:
            seen_urls[url] = item.id
        out.append(item)
    return out


def _listing_urls(slices: list[SourceSlice]) -> set[str]:
    shared: set[str] = set()
    for s in slices:
        counts: dict[str, int] = {}
        for e in s.events:
            if e.source_url:
                counts[str(e.source_url)] = counts.get(str(e.source_url), 0) + 1
        shared |= {u for u, n in counts.items() if n > 1}
    return shared


def _scenarios(fixture_scenarios: list[dict[str, Any]], events: list[Event]) -> list[dict[str, Any]]:
    ids = {e.id for e in events}
    kept = [s for s in fixture_scenarios
            if all(c.get("event_id") in ids for c in s.get("changes", []))]
    if kept:
        return kept
    target = next((e for e in events if e.event_type in {"side_event", "party", "meetup"}
                   and e.status == "scheduled"), None) or next(iter(events), None)
    if target is None:
        return []
    return [{
        "id": "w15-simulated-sold-out",
        "label": f"SIMULATION (not observed): {target.title[:60]} becomes sold out",
        "changes": [{"event_id": target.id, "set": {"status": "sold_out"}}],
    }]


def assemble(slices: list[SourceSlice]) -> Assembly:
    now = datetime.now(timezone.utc)
    api_fixture = load_api_fixture()
    warnings: list[str] = []
    official = next((s for s in slices if s.conference is not None), None)
    if official and official.conference:
        conference, origin = official.conference, f"{official.name} ({official.source_mode})"
    else:
        conference, origin = api_fixture.conference, "fixtures/api.json (fixture)"
        warnings.append("anchor conference from API fixture: no source produced a Conference")
    if api_fixture.conference.id != conference.id:
        warnings.append(
            f"conference id mismatch: API fixture uses {api_fixture.conference.id!r}, "
            f"assembled data uses {conference.id!r}"
        )
    duplicates: list[str] = []
    ids: set[str] = set()
    urls: dict[str, str] = {}
    events = _dedup([e for s in slices for e in s.events], ids, urls, duplicates,
                    _listing_urls(slices))
    people = _dedup([p for s in slices for p in s.people], set(), {}, duplicates)
    companies = _dedup([c for s in slices for c in s.companies], set(), {}, duplicates)

    fixture_domains = api_fixture.domains
    domains = {
        "conference": DomainSlice(
            official.source_mode if official else "fixture",
            official.status if official else "degraded",
            official.collected_at or now if official else fixture_domains["conference"].collected_at,
            [f"conference from {origin}"],
        ),
        "events": _domain(slices, "events", now),
        "people": _domain(slices, "people", now),
        "companies": _domain(slices, "companies", now),
    }
    for name, window in (("stays", "w05 lodging"), ("flights", "w06 flights")):
        base = fixture_domains[name]
        domains[name] = DomainSlice("fixture", "degraded", base.collected_at,
                                    [*base.warnings, f"{window} not merged: API fixture used"])
    demo = DemoData(
        conference=conference,
        user=dict(api_fixture.user),
        demo_goal_text=api_fixture.demo_goal_text,
        events=events,
        people=people,
        companies=companies,
        stays=list(api_fixture.stays),
        flights=list(api_fixture.flights),
        scenarios=_scenarios(api_fixture.scenarios, events),
        domains=domains,
    )
    return Assembly(conference, origin, events, people, companies, slices, demo,
                    duplicates, warnings)
