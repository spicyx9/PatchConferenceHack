"""Local container for one graph load (w08-owned, not a shared contract)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from conferge.core.schemas import (
    Company,
    Conference,
    Event,
    FlightOffer,
    Goal,
    Lodging,
    Opportunity,
    Person,
    SourceMode,
)
from conferge.core.store import GraphStore
from conferge.graph.ingest import GraphIngestor, IngestReport
from conferge.graph.schema import venue_id
from conferge.graph.textgraph import DEFAULT_VOCABULARY, link_text_topics


class GraphBundle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_mode: SourceMode
    note: str | None = None
    user_id: str = "demo-user"
    conference: Conference
    companies: list[Company] = Field(default_factory=list)
    people: list[Person] = Field(default_factory=list)
    events: list[Event] = Field(default_factory=list)
    goals: list[Goal] = Field(default_factory=list)
    opportunities: list[Opportunity] = Field(default_factory=list)
    lodging: list[Lodging] = Field(default_factory=list)
    flights: list[FlightOffer] = Field(default_factory=list)


def ingest_bundle(store: GraphStore, bundle: GraphBundle, *,
                  link_text: bool = True) -> IngestReport:
    """Dependency-ordered load: nodes that edges point to are merged first."""
    ing = GraphIngestor(store, default_mode=bundle.source_mode)
    ing.ingest_companies(bundle.companies)
    ing.ingest_people(bundle.people)
    ing.ingest_conference(bundle.conference)
    ing.ingest_events(bundle.events)
    ing.link_participation(bundle.people)
    ing.ingest_goals(bundle.user_id, bundle.goals)
    if link_text:
        vocabulary = dict(DEFAULT_VOCABULARY)
        for goal in bundle.goals:
            for name in goal.topics:
                vocabulary.setdefault(name, ())
        for person in bundle.people:
            link_text_topics(ing, "Person", person.id, person.bio, person.evidence,
                             vocabulary, declared=person.topics)
        for event in bundle.events:
            link_text_topics(ing, "Event", event.id, event.description, event.evidence,
                             vocabulary, declared=event.topics)
    ing.ingest_opportunities(bundle.opportunities)
    conf = bundle.conference
    ing.ingest_lodging(bundle.lodging, venue_id(conf.venue_name, None, conf.city))
    ing.ingest_flights(bundle.flights)
    return ing.report
