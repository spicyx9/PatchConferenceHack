"""Canonical node/edge mapping for the Conferge opportunity graph.

The write vocabulary is fixed by ``conferge.core.store`` (window 0). This module
documents how each pydantic model maps onto that vocabulary and holds the
stable-id helpers shared by ingestion, queries and explanations.

Mapping (pydantic -> graph), restricted to labels/edges allowed by GraphStore:

    Conference               (:Conference)
    Event (any event_type)   (:Event {event_type})
    Person                   (:Person)
    Company                  (:Company)
    Goal                     (:Goal {user_id})
    Venue                    (:Venue)
    topics / categories      (:Topic)
    Opportunity              (:Opportunity)
    Lodging / FlightOffer    (:Lodging) / (:FlightOffer)
    user memory              (:Meeting {user_id, kind, at, at_ms, target_id, reason?})

    (Event)-[:PART_OF {relation, relation_score}]->(Conference)
    (Event|Person|Goal|Conference)-[:ABOUT {kind}]->(Topic)
    (Event|Conference)-[:LOCATED_AT]->(Venue)
    (Person)-[:SPEAKS_AT]->(Event)
    (Person|Company)-[:HOSTS]->(Event)
    (Person)-[:WORKS_AT {role, title}]->(Company)
    (Person)-[:ATTENDS_CONFIRMED {evidence_url}]->(Event)   evidence required
    (Company)-[:EXHIBITS_AT {role: "sponsor"}]->(Conference)
    (Opportunity)-[:SERVES_GOAL]->(Goal)
    (Opportunity)-[:INVOLVES]->(Person|Company|Event)
    (Lodging)-[:NEAR {distance_m}]->(Venue)
    (Meeting)-[:MET]->(Person)            kind == MET
    (Meeting)-[:INVOLVES]->(Person|Event) kind in ATTENDED, SKIPPED, CONTACTED

Every edge carries ``source``, ``source_mode``, ``confidence``, ``observed_at``
(None when the source has no timestamp; never the ingest time) and
``verification``. Every node carries ``source``, ``source_mode`` and
``ingested_at``.

Notes on gaps (see the w08 PR "Proposition fenetre 0"): there is no ``User``
label nor ``TARGETS``/``AROUND``/``INTERESTED_IN``/``SPONSORS`` edge in the
allow-list, so goals hang off ``Goal.user_id`` and the side-event to conference
link is ``PART_OF`` with a ``relation`` property mirroring
``Event.conference_relation``.
"""

from __future__ import annotations

import re
import unicodedata

NODE_LABELS = (
    "Conference", "Event", "Person", "Company", "Goal", "Opportunity", "Venue",
    "Topic", "Lodging", "FlightOffer", "Meeting",
)
EDGE_TYPES = (
    "PART_OF", "SPEAKS_AT", "HOSTS", "WORKS_AT", "ATTENDS_CONFIRMED", "ABOUT",
    "LOCATED_AT", "SERVES_GOAL", "NEAR", "INVOLVES", "MET", "EXHIBITS_AT",
)
MEMORY_KINDS = ("MET", "ATTENDED", "SKIPPED", "CONTACTED")

# Read-only DDL that window 0 may run once on a fresh graph. Kept as data here:
# index creation is a schema operation, not a node/edge write, and is never
# executed implicitly by this package.
INDEX_STATEMENTS = tuple(
    f"CREATE INDEX FOR (n:{label}) ON (n.id)" for label in NODE_LABELS
) + (
    "CALL db.idx.fulltext.createNodeIndex('Topic', 'name')",
    "CALL db.idx.fulltext.createNodeIndex('Person', 'name')",
    "CALL db.idx.fulltext.createNodeIndex('Event', 'title')",
)

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slug(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return _SLUG_RE.sub("-", normalized.lower()).strip("-")


def topic_id(name: str) -> str:
    return f"topic:{slug(name)}"


def venue_id(name: str | None, address: str | None, city: str | None) -> str | None:
    key = name or address
    if not key:
        return None
    return f"venue:{slug(' '.join(part for part in (key, city) if part))}"


