"""Idempotent graph ingestion of normalized ``conferge.core.schemas`` models.

All writes go through ``GraphStore.merge_node`` / ``merge_edge``; this module
never builds Cypher. Unknown values are omitted (FalkorDB treats a missing
property as null), never replaced by defaults.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from conferge.core.schemas import (
    Company,
    Conference,
    Event,
    FlightOffer,
    Goal,
    Lodging,
    Opportunity,
    Person,
    SourceEvidence,
    SourceMode,
    Venue,
)
from conferge.core.store import GraphStore
from conferge.graph.schema import topic_id, venue_id

_RELATION_CONFIDENCE = {"official": 1.0, "confirmed_side_event": 0.9, "candidate": 0.5}


def _scalar(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (list, tuple)):
        return [_scalar(item) for item in value]
    if hasattr(value, "unicode_string"):  # pydantic HttpUrl
        return str(value)
    return value


def _clean(props: dict[str, Any]) -> dict[str, Any]:
    return {key: _scalar(value) for key, value in props.items() if value is not None}


def _epoch(value: datetime | None) -> int | None:
    return int(value.timestamp()) if value is not None else None


@dataclass
class IngestReport:
    nodes: int = 0
    edges: int = 0
    corroborated_edges: int = 0
    skipped_edges: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class GraphIngestor:
    """Maps pydantic models to GraphStore MERGE calls.

    ``default_mode`` labels records that carry no evidence; callers must pass
    the mode their data really comes from (fixture data stays ``fixture``).
    """

    def __init__(self, store: GraphStore, *, default_mode: SourceMode,
                 ingested_at: datetime | None = None) -> None:
        self.store = store
        self.default_mode = default_mode
        self.ingested_at = (ingested_at or datetime.now(timezone.utc)).isoformat()
        self.report = IngestReport()
        self._nodes: dict[str, set[str]] = {}
        self._edges: set[tuple[str, str, str]] = set()

    # -- primitives -----------------------------------------------------------------

    def _provenance(self, evidence: list[SourceEvidence]) -> dict[str, Any]:
        first = evidence[0] if evidence else None
        return _clean({
            "source": first.provider if first else None,
            "source_mode": first.source_mode if first else self.default_mode,
            "source_url": first.source_url if first else None,
            "observed_at": first.collected_at if first else None,
            "confidence": first.confidence if first else None,
            "evidence_count": len(evidence),
        })

    def write_node(self, kind: str, node_id: str, props: dict[str, Any],
                   evidence: list[SourceEvidence] | None = None) -> None:
        payload = {**self._provenance(evidence or []), **_clean(props),
                   "ingested_at": self.ingested_at}
        self.store.merge_node(kind, node_id, payload)
        self._nodes.setdefault(kind, set()).add(node_id)
        self.report.nodes += 1

    def write_edge(self, from_kind: str, from_id: str, edge_type: str, to_kind: str,
                   to_id: str, *, evidence: list[SourceEvidence] | None = None, verification: str,
                   confidence: float | None = None, **props: Any) -> None:
        # The first writer of an edge keeps its provenance: a second source
        # (e.g. the person record repeating an event speaker list) corroborates
        # it instead of overwriting verification/source.
        key = (from_id, edge_type, to_id)
        if key in self._edges:
            self.report.corroborated_edges += 1
            return
        self._edges.add(key)
        payload = {**self._provenance(evidence or []), **_clean(props),
                   "verification": verification}
        if confidence is not None:
            payload["confidence"] = confidence
        self.store.merge_edge(from_kind, from_id, edge_type, to_kind, to_id, payload)
        self.report.edges += 1

    def has(self, kind: str, node_id: str) -> bool:
        return node_id in self._nodes.get(kind, set())

    def _topics(self, from_kind: str, from_id: str, topics: Iterable[str], *, kind: str,
                evidence: list[SourceEvidence], verification: str,
                source: str | None = None) -> None:
        for name in dict.fromkeys(t.strip() for t in topics if t and t.strip()):
            tid = topic_id(name)
            if not tid.removeprefix("topic:"):
                continue
            if not self.has("Topic", tid):
                self.write_node("Topic", tid, {"name": name, "source": source}, evidence)
            self.write_edge(from_kind, from_id, "ABOUT", "Topic", tid, evidence=evidence,
                            verification=verification, kind=kind, source=source)

    def _venue(self, venue: Venue | None, evidence: list[SourceEvidence]) -> str | None:
        if venue is None:
            return None
        vid = venue_id(venue.name, venue.address, venue.city)
        if vid is None:
            return None
        if not self.has("Venue", vid):
            self.write_node("Venue", vid, {
                "name": venue.name, "address": venue.address, "city": venue.city,
                "latitude": venue.latitude, "longitude": venue.longitude,
                "coordinate_precision": venue.coordinate_precision,
            }, evidence)
        return vid

    # -- models -------------------------------------------------------------------

    def ingest_conference(self, conf: Conference) -> None:
        self.write_node("Conference", conf.id, {
            "name": conf.name, "start_date": conf.start_date.isoformat(),
            "end_date": conf.end_date.isoformat(), "city": conf.city,
            "venue_name": conf.venue_name, "timezone": conf.timezone,
            "official_url": conf.official_url, "latitude": conf.latitude,
            "longitude": conf.longitude, "topics": conf.topics,
        }, conf.evidence)
        self._topics("Conference", conf.id, conf.topics, kind="program",
                     evidence=conf.evidence, verification="conference_record")
        vid = self._venue(Venue(name=conf.venue_name, city=conf.city, latitude=conf.latitude,
                                longitude=conf.longitude,
                                coordinate_precision="approximate" if conf.latitude is not None else "unknown")
                          if conf.venue_name else None, conf.evidence)
        if vid:
            self.write_edge("Conference", conf.id, "LOCATED_AT", "Venue", vid,
                       evidence=conf.evidence, verification="conference_record")
        for company in conf.sponsor_ids:
            if self.has("Company", company):
                self.write_edge("Company", company, "EXHIBITS_AT", "Conference", conf.id,
                           evidence=conf.evidence, verification="sponsor_list", role="sponsor")
            else:
                self.report.skipped_edges.append(f"sponsor {company} unknown company")

    def ingest_companies(self, companies: Iterable[Company]) -> None:
        for company in companies:
            self.write_node("Company", company.id, {
                "name": company.name, "domain": company.domain,
                "linkedin_url": company.linkedin_url, "industry": company.industry,
                "is_investor": company.is_investor, "categories": company.categories,
            }, company.evidence)

    def ingest_people(self, people: Iterable[Person]) -> None:
        for person in people:
            self.write_node("Person", person.id, {
                "name": person.name, "role": person.role, "title": person.title,
                "public_profile_url": person.public_profile_url,
                "linkedin_url": person.linkedin_url, "github_url": person.github_url,
                "x_handle": person.x_handle, "bio": person.bio, "topics": person.topics,
                "roles": person.roles, "participation": person.participation,
                "match_confidence": person.match_confidence,
            }, person.evidence)
            if person.company_id:
                if self.has("Company", person.company_id):
                    self.write_edge("Person", person.id, "WORKS_AT", "Company", person.company_id,
                               evidence=person.evidence, verification="person_record",
                               role=person.role, title=person.title)
                else:
                    self.report.skipped_edges.append(
                        f"WORKS_AT {person.id}->{person.company_id}: company not ingested")
            self._topics("Person", person.id, person.topics, kind="interest",
                         evidence=person.evidence, verification="person_record")

    def ingest_events(self, events: Iterable[Event]) -> None:
        for event in events:
            self.write_node("Event", event.id, {
                "title": event.title, "name": event.title, "description": event.description,
                "event_type": event.event_type, "start_at": event.start_at,
                "end_at": event.end_at, "start_ts": _epoch(event.start_at),
                "end_ts": _epoch(event.end_at), "timezone": event.timezone,
                "room": event.room, "status": event.status,
                "conference_relation": event.conference_relation,
                "relation_score": event.relation_score,
                "registration_url": event.registration_url, "event_url": event.source_url,
                "is_free": event.is_free, "price_min": event.price_min,
                "price_max": event.price_max, "currency": event.currency,
                "capacity": event.capacity, "registered_count": event.registered_count,
                "organizer_names": event.organizer_names, "topics": event.topics,
            }, event.evidence)
            if event.conference_id and event.conference_relation != "unrelated":
                if self.has("Conference", event.conference_id):
                    self.write_edge("Event", event.id, "PART_OF", "Conference", event.conference_id,
                               evidence=event.evidence,
                               verification=("relation_evidence" if event.relation_evidence
                                             else "unverified"),
                               confidence=event.relation_score
                               if event.relation_score is not None
                               else _RELATION_CONFIDENCE.get(event.conference_relation),
                               relation=event.conference_relation,
                               relation_score=event.relation_score,
                               relation_evidence=event.relation_evidence)
                else:
                    self.report.skipped_edges.append(
                        f"PART_OF {event.id}: conference {event.conference_id} not ingested")
            self._topics("Event", event.id, event.topics, kind="program",
                         evidence=event.evidence, verification="event_record")
            vid = self._venue(event.venue, event.evidence)
            if vid:
                self.write_edge("Event", event.id, "LOCATED_AT", "Venue", vid,
                           evidence=event.evidence, verification="event_record")
            for speaker in event.speaker_ids:
                if self.has("Person", speaker):
                    self.write_edge("Person", speaker, "SPEAKS_AT", "Event", event.id,
                               evidence=event.evidence, verification="event_speaker_list")
                else:
                    self.report.skipped_edges.append(
                        f"SPEAKS_AT {speaker}->{event.id}: person not ingested")
            for organizer in event.organizer_ids:
                kind = ("Company" if self.has("Company", organizer)
                        else "Person" if self.has("Person", organizer) else None)
                if kind is None:
                    self.report.skipped_edges.append(
                        f"HOSTS {organizer}->{event.id}: organizer not ingested")
                    continue
                self.write_edge(kind, organizer, "HOSTS", "Event", event.id,
                           evidence=event.evidence, verification="event_organizer_list")

    def link_participation(self, people: Iterable[Person]) -> None:
        """Person-side participation edges; run after people and events.

        Speaker and organizer roles create SPEAKS_AT / HOSTS. Attendance needs
        a public attendee listing *with* evidence carrying a source URL; any
        other participation (``relevant_candidate``, ``unknown``) never yields
        an attendance edge.
        """
        for person in people:
            for event in person.event_ids:
                if not self.has("Event", event):
                    self.report.skipped_edges.append(
                        f"participation {person.id}->{event}: event not ingested")
                    continue
                if person.participation == "confirmed_speaker":
                    self.write_edge("Person", person.id, "SPEAKS_AT", "Event", event,
                               evidence=person.evidence, verification="person_record")
                elif person.participation == "confirmed_organizer":
                    self.write_edge("Person", person.id, "HOSTS", "Event", event,
                               evidence=person.evidence, verification="person_record")
                elif person.participation == "public_attendee_listing":
                    urls = [e for e in person.evidence if e.source_url is not None]
                    if not urls:
                        self.report.skipped_edges.append(
                            f"ATTENDS_CONFIRMED {person.id}->{event}: no evidence URL")
                        continue
                    self.write_edge("Person", person.id, "ATTENDS_CONFIRMED", "Event", event,
                               evidence=urls, verification="public_attendee_listing",
                               evidence_url=str(urls[0].source_url), status="confirmed")

    def ingest_goals(self, user_id: str, goals: Iterable[Goal]) -> None:
        for goal in goals:
            self.write_node("Goal", goal.id, {
                "source": "user", "user_id": user_id, "description": goal.description,
                "name": goal.description,
                "priority": goal.priority, "tags": goal.tags, "topics": goal.topics,
                "target_roles": goal.target_roles, "target_count": goal.target_count,
            })
            self._topics("Goal", goal.id, goal.topics, kind="targets", evidence=[],
                         verification="user_goal", source="user")

    def ingest_opportunities(self, opportunities: Iterable[Opportunity]) -> None:
        for opp in opportunities:
            self.write_node("Opportunity", opp.id, {
                "title": opp.title, "name": opp.title, "score": opp.score,
                "rationale": opp.rationale, "where": opp.where, "opener": opp.opener,
                "presence": opp.presence, "warnings": opp.warnings,
            }, opp.evidence)
            targets = [("Goal", g, "SERVES_GOAL") for g in opp.goal_ids]
            targets += [("Person", p, "INVOLVES") for p in opp.person_ids]
            targets += [("Company", c, "INVOLVES") for c in opp.company_ids]
            if opp.event_id:
                targets.append(("Event", opp.event_id, "INVOLVES"))
            for kind, target, relation in targets:
                if self.has(kind, target):
                    self.write_edge("Opportunity", opp.id, relation, kind, target,
                               evidence=opp.evidence, verification="agent_output",
                               score=opp.score)
                else:
                    self.report.skipped_edges.append(f"{relation} {opp.id}->{target}: missing")

    def ingest_lodging(self, lodgings: Iterable[Lodging], near_venue_id: str | None = None) -> None:
        for stay in lodgings:
            self.write_node("Lodging", stay.id, {
                "name": stay.name, "provider": stay.provider, "lodging_type": stay.lodging_type,
                "check_in": stay.check_in.isoformat(), "check_out": stay.check_out.isoformat(),
                "adults": stay.adults, "total_price": stay.total_price,
                "currency": stay.currency, "price_status": stay.price_status,
                "availability": stay.availability, "verified_at": stay.verified_at,
                "booking_url": stay.booking_url, "distance_to_venue_m": stay.distance_to_venue_m,
                "latitude": stay.venue.latitude if stay.venue else None,
                "longitude": stay.venue.longitude if stay.venue else None,
            }, stay.evidence)
            if near_venue_id and stay.distance_to_venue_m is not None and self.has(
                "Venue", near_venue_id
            ):
                self.write_edge("Lodging", stay.id, "NEAR", "Venue", near_venue_id,
                           evidence=stay.evidence, verification="provider_distance",
                           distance_m=stay.distance_to_venue_m)

    def ingest_flights(self, offers: Iterable[FlightOffer]) -> None:
        for offer in offers:
            first, last = offer.slices[0].segments[0], offer.slices[0].segments[-1]
            self.write_node("FlightOffer", offer.id, {
                "trip_type": offer.trip_type, "origin_iata": first.origin_iata,
                "destination_iata": last.destination_iata,
                "departure_at": first.departure_at, "stops": offer.slices[0].stops,
                "total_price": offer.total_price, "currency": offer.currency,
                "price_scope": offer.price_scope, "price_status": offer.price_status,
                "collected_at": offer.collected_at, "booking_url": offer.booking_url,
                "warnings": offer.warnings,
            }, offer.evidence)
