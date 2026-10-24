"""Stage A: gather public people from already-normalized sources.

- Official speakers (w03 `conferge.events.official`): presence `confirmed` on the sessions
  where the official catalog lists them, nothing else.
- Luma hosts (w01 `conferge.events.luma`): public host list of a public event page;
  presence `confirmed` as host of that event only.
- Luma guest lists, Partiful guests or any roster behind a login are never read.

Fixture loading is explicit (`collect_fixtures`) and every record keeps the source mode
of the record it came from.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from conferge.core.schemas import (
    Company,
    DataMode,
    Event,
    Person,
    RunReport,
    RunStatus,
    SourceEvidence,
    SourceRecord,
)
from conferge.people.models import Presence, PersonProfile
from conferge.people.taxonomy import roles_from_title, topics_from_text


@dataclass
class CollectedPeople:
    profiles: list[PersonProfile]
    events: list[Event]
    companies: list[Company]
    reports: list[RunReport] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def source_mode(self) -> DataMode:
        return combine_modes(r.source_mode for r in self.reports)

    @property
    def status(self) -> RunStatus:
        statuses = {r.status for r in self.reports}
        if not statuses or statuses == {"failed"}:
            return "failed"
        return "ok" if statuses == {"ok"} else "degraded"


def combine_modes(modes: Iterable[str]) -> DataMode:
    unique = set(modes)
    if not unique:
        return "fixture"
    if len(unique) == 1:
        return unique.pop()  # type: ignore[return-value]
    return "mixed"


def _first_evidence(person: Person) -> SourceEvidence | None:
    return person.evidence[0] if person.evidence else None


def from_official(people: Iterable[Person], events: Iterable[Event],
                  companies: Iterable[Company]) -> list[PersonProfile]:
    """Wrap official catalog people; confirmed only for their listed sessions."""
    by_event = {e.id: e for e in events}
    company_names = {c.id: c.name for c in companies}
    profiles: list[PersonProfile] = []
    for person in people:
        evidence = _first_evidence(person)
        presences: list[Presence] = []
        talks: list[str] = []
        event_topics: list[str] = []
        for event_id in person.event_ids:
            event = by_event.get(event_id)
            if event is not None:
                talks.append(event.title)
                event_topics.extend(event.topics)
            if evidence is None:
                continue
            ev = evidence
            if event is not None and event.source_url is not None:
                ev = evidence.model_copy(update={"source_url": event.source_url})
            confirmed = person.participation == "confirmed_speaker"
            presences.append(Presence(
                event_id=event_id,
                kind="speaker" if confirmed else "candidate",
                status="confirmed" if confirmed else "unknown",
                evidence=ev,
            ))
        topics = list(person.topics)
        for topic in topics_from_text(person.bio, person.title, *talks, *event_topics):
            if topic not in topics:
                topics.append(topic)
        # Re-derive from the title with the stricter w07 rules ("Tech Lead Venture" is
        # not an investor); keep source roles only when there is no title.
        roles = roles_from_title(person.title) if person.title else list(person.roles)
        profiles.append(PersonProfile(
            person=person.model_copy(update={
                "topics": topics, "roles": roles,
                # Identity comes from the organizer itself, not from a search match.
                "identity_confidence": person.identity_confidence or 1.0,
            }),
            company_name=company_names.get(person.company_id or ""),
            presences=presences,
            talk_titles=talks,
            merged_from=[person.id],
        ))
    return profiles


def from_luma(records: Iterable[SourceRecord], events: Iterable[Event]) -> list[PersonProfile]:
    """Public hosts listed on public Luma event pages; one presence per hosted event."""
    by_source = {event.id: event for event in events}
    profiles: dict[str, PersonProfile] = {}
    for record in records:
        event = _luma_event_for(record, by_source)
        if event is None:
            continue
        for host in record.payload.get("hosts") or []:
            if not isinstance(host, dict) or not host.get("api_id") or not host.get("name"):
                continue
            pid = f"person:luma:{host['api_id']}"
            evidence = SourceEvidence(
                provider=record.provider, source_mode=record.source_mode,
                source_url=record.source_url, collected_at=record.collected_at,
                source_record_id=str(host["api_id"]), confidence=1.0,
            )
            presence = Presence(event_id=event.id, kind="host", status="confirmed",
                                evidence=evidence)
            existing = profiles.get(pid)
            if existing is None:
                name = str(host["name"]).strip()
                profiles[pid] = PersonProfile(
                    person=Person(
                        id=pid, name=name, evidence=[evidence],
                        topics=topics_from_text(event.title, event.description, *event.topics),
                        identity_confidence=None,
                    ),
                    presences=[presence],
                    talk_titles=[],
                    merged_from=[pid],
                )
            elif all(p.event_id != event.id for p in existing.presences):
                topics = list(existing.person.topics)
                for t in topics_from_text(event.title, event.description, *event.topics):
                    if t not in topics:
                        topics.append(t)
                existing.person = existing.person.model_copy(update={
                    "topics": topics, "evidence": [*existing.person.evidence, evidence],
                })
                existing.presences = [*existing.presences, presence]
    return list(profiles.values())


def _luma_event_for(record: SourceRecord, events: dict[str, Event]) -> Event | None:
    # conferge.events.luma.normalize builds ids as "luma:<source_id>".
    return events.get(f"luma:{record.source_id}")


def collect_fixtures(*, explicit_opt_in: bool = False) -> CollectedPeople:
    """Replay the official and Luma fixtures (real public captures) offline.

    Only called on explicit request (probe, demo fallback, tests). Output is fixture.
    """
    if not explicit_opt_in:
        raise RuntimeError("fixture use must be explicitly requested (explicit_opt_in=True)")
    from conferge.events import luma, official

    off = official.load_fixture(explicit_opt_in=True)
    lu = luma.load_fixture(explicit_opt_in=True)
    luma_events = [luma.normalize(r, conference_id=official.CONFERENCE_ID) for r in lu.items]
    profiles = from_official(off.people.items, off.events.items, off.companies.items)
    profiles += from_luma(lu.items, luma_events)
    return CollectedPeople(
        profiles=profiles,
        events=[*off.events.items, *luma_events],
        companies=list(off.companies.items),
        reports=[*off.people.reports, lu.run_report],
        warnings=list(off.warnings),
    )
