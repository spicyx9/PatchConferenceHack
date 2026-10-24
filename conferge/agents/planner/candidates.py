"""Turn normalized ``AgentContext`` facts into scoring ``Candidate`` objects.

Only facts present in the context are used. Presence follows the core rule:
a public speaker is *confirmed* only at the event that lists them (speaker or
organizer) or that their own record ties to as speaker/organizer; any other
link is *probable* at best. Every fact string cites provider, source mode,
URL (or raw_ref) and ``collected_at``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Literal

from conferge.agents.planner.geo import estimate
from conferge.agents.planner.goals import normalized_weights
from conferge.agents.planner.scoring import Candidate
from conferge.agents.planner.text import role_set, roles_from_title, topic_set
from conferge.core.schemas import AgentContext, Event, Goal, Person, SourceEvidence, Venue

Presence = Literal["confirmed", "probable", "unknown"]
PRESENCE_VALUE: dict[str, float] = {"confirmed": 1.0, "probable": 0.5, "unknown": 0.0}
PRESENCE_RANK: dict[str, int] = {"confirmed": 0, "probable": 1, "unknown": 2}
TIME_NORM_MIN = 240.0       # 4 h of duration + travel saturates T
COST_NORM_USD = Decimal("200")
UNSCHEDULABLE = {"cancelled", "sold_out"}
_SPEAKING_TYPES = {"session", "workshop", "conference"}
_VENUE_UNCERTAINTY = {"exact": 0.0, "approximate": 0.25, "city": 0.5, "unknown": 1.0}


def cite(evidence: list[SourceEvidence]) -> str:
    if not evidence:
        return "no source evidence"
    ev = max(evidence, key=lambda e: e.confidence if e.confidence is not None else -1)
    where = str(ev.source_url) if ev.source_url else (ev.raw_ref or "no url")
    when = ev.collected_at.isoformat() if ev.collected_at else "collected_at unknown"
    return f"{ev.provider}/{ev.source_mode} {where} @ {when}"


def evidence_uncertainty(evidence: list[SourceEvidence]) -> float:
    if not evidence:
        return 1.0
    known = [e.confidence for e in evidence if e.confidence is not None]
    return round(1.0 - max(known), 4) if known else 0.5


def venue_uncertainty(venue: Venue | None) -> float:
    if venue is None or (venue.latitude is None and not venue.name):
        return 1.0
    return _VENUE_UNCERTAINTY.get(venue.coordinate_precision, 1.0)


def duration_min(event: Event) -> int | None:
    if event.start_at and event.end_at:
        return int((event.end_at - event.start_at).total_seconds() // 60)
    return None


def known_cost(event: Event) -> Decimal | None:
    """USD cost when stated; ``None`` means unknown, never zero."""
    if event.is_free is True:
        return Decimal("0")
    if event.price_min is None or (event.currency and event.currency != "USD"):
        return None
    try:
        return Decimal(event.price_min)
    except InvalidOperation:
        return None


def event_label(event: Event) -> str:
    when = event.start_at.isoformat() if event.start_at else "time unknown"
    venue = event.venue.name if event.venue and event.venue.name else "venue unknown"
    room = f", {event.room}" if event.room else ""
    return f"{event.title} ({when}, {venue}{room})"


@dataclass
class GoalMatch:
    role: float          # 1 explicit role, 0.5 role read from title, 0 none
    topic: float         # share of goal topics the person covers
    role_basis: str

    @property
    def value(self) -> float:
        return 0.7 * self.role + 0.3 * self.topic


def person_goal_match(person: Person, goal: Goal) -> GoalMatch:
    targets = role_set(goal.target_roles)
    goal_topics = topic_set(goal.topics)
    topic = (len(topic_set(person.topics) & goal_topics) / len(goal_topics)) if goal_topics else 0.0
    explicit = role_set([*person.roles, *([person.role] if person.role else [])])
    if targets & explicit:
        return GoalMatch(1.0, topic, f"role {sorted(targets & explicit)[0]}")
    if targets & roles_from_title(person.title):
        return GoalMatch(0.5, topic, f"title '{person.title}' suggests {sorted(targets)[0]}")
    return GoalMatch(0.0, topic, "no role match")


@dataclass
class World:
    """Indexes over the context, shared by person and event candidates."""

    ctx: AgentContext
    met: set[str] = field(default_factory=set)
    met_companies: set[str] = field(default_factory=set)

    def __post_init__(self) -> None:
        self.weights = normalized_weights(self.ctx.goals)
        self.events = {e.id: e for e in self.ctx.events}
        self.people = {p.id: p for p in self.ctx.people}
        self.matches: dict[str, dict[str, GoalMatch]] = {
            p.id: {g.id: person_goal_match(p, g) for g in self.ctx.goals} for p in self.ctx.people
        }
        self.anchor = Venue(
            name=self.ctx.conference.venue_name, city=self.ctx.conference.city,
            latitude=self.ctx.conference.latitude, longitude=self.ctx.conference.longitude,
            coordinate_precision="exact" if self.ctx.conference.latitude is not None else "unknown",
        )

    def presence(self, person: Person, event: Event) -> tuple[Presence, str]:
        if person.id in event.speaker_ids:
            return "confirmed", f"listed as speaker of '{event.title}' ({cite(event.evidence)})"
        if person.id in event.organizer_ids:
            return "confirmed", f"listed as organizer of '{event.title}' ({cite(event.evidence)})"
        if event.id in person.event_ids:
            if person.participation == "confirmed_speaker" and event.event_type in _SPEAKING_TYPES:
                return "confirmed", f"speaker record links to '{event.title}' ({cite(person.evidence)})"
            if person.participation == "confirmed_organizer":
                return "confirmed", f"organizer record links to '{event.title}' ({cite(person.evidence)})"
            if person.participation in {"public_attendee_listing", "confirmed_speaker"}:
                return "probable", (f"{person.participation} links to '{event.title}', not a "
                                    f"confirmed attendance ({cite(person.evidence)})")
            return "unknown", f"weak link to '{event.title}' ({cite(person.evidence)})"
        return "unknown", "no source ties this person to the event"

    def person_events(self, person: Person) -> list[tuple[Event, Presence, str]]:
        ids = set(person.event_ids) | {
            e.id for e in self.ctx.events if person.id in e.speaker_ids or person.id in e.organizer_ids
        }
        out = []
        for event_id in ids:
            event = self.events.get(event_id)
            if event is None or event.status in UNSCHEDULABLE:
                continue
            presence, why = self.presence(person, event)
            out.append((event, presence, why))
        far_future = "9999"
        out.sort(key=lambda t: (PRESENCE_RANK[t[1]],
                                t[0].start_at.isoformat() if t[0].start_at else far_future, t[0].id))
        return out

    def is_target(self, person_id: str) -> bool:
        return any(m.role > 0 for m in self.matches.get(person_id, {}).values())


def person_candidate(world: World, person: Person) -> tuple[Candidate, Event | None, Presence] | None:
    matches = world.matches[person.id]
    goal_value = sum(world.weights[g] * m.value for g, m in matches.items())
    if goal_value <= 0:
        return None
    goals = {g.id: g for g in world.ctx.goals}
    best_goal_id = max(matches, key=lambda g: (world.weights[g] * matches[g].value, g))
    best = matches[best_goal_id]
    role_strength = max(m.role for m in matches.values())
    topic_value = sum(world.weights[g] * m.topic for g, m in matches.items())
    events = world.person_events(person)
    event, presence, presence_why = events[0] if events else (None, "unknown", "no linked event")

    facts = [
        f"{best.role_basis} serves goal '{goals[best_goal_id].description}' "
        f"(weight {world.weights[best_goal_id]:.2f}) ({cite(person.evidence)})",
        f"presence {presence}: {presence_why}",
    ]
    notes = {"G": best.role_basis, "P": f"presence {presence}"}
    if person.company_id in world.met_companies:
        novelty = 0.0
        notes["N"] = f"company {person.company_id} already covered by a met contact"
    elif person.company_id:
        novelty = 1.0
    else:
        novelty, notes["N"] = 0.5, "company unknown"

    time_value = cost_value = 0.0
    if event is not None:
        minutes = duration_min(event)
        if minutes is not None:
            time_value = min(minutes / TIME_NORM_MIN, 1.0)
        else:
            notes["T"] = "event time unknown"
        cost = known_cost(event)
        if cost is None:
            notes["C"] = "price unknown"
        else:
            cost_value = float(min(cost / COST_NORM_USD, Decimal(1)))
        facts.append(f"where: {event_label(event)} ({cite(event.evidence)})")
    # v0.2.1 Person confidences, when a source window provides them, override defaults.
    presence_unc = 1.0 - PRESENCE_VALUE[presence]
    if person.presence_confidence is not None and presence != "unknown":
        presence_unc = 1.0 - person.presence_confidence
    identity_unc = evidence_uncertainty(person.evidence)
    if person.identity_confidence is not None:
        identity_unc = max(identity_unc, 1.0 - person.identity_confidence)
    uncertainty = (presence_unc + identity_unc
                   + (venue_uncertainty(event.venue) if event else 1.0)) / 3
    path = [{"source": f"Goal:{best_goal_id}", "type": "TARGETS_ROLE",
             "target": f"Person:{person.id}", "evidence": best.role_basis}]
    if event is not None:
        rel = "SPEAKS_AT" if person.id in event.speaker_ids else (
            "HOSTS" if person.id in event.organizer_ids else "LINKED_TO")
        path.append({"source": f"Person:{person.id}", "type": rel, "target": f"Event:{event.id}",
                     "presence": presence, "evidence": presence_why})
    if person.company_id:
        path.append({"source": f"Person:{person.id}", "type": "WORKS_AT",
                     "target": f"Company:{person.company_id}", "evidence": cite(person.evidence)})

    candidate = Candidate(
        kind="person", id=person.id,
        goal=round(min(goal_value, 1.0), 4),
        people=round(PRESENCE_VALUE[presence] * role_strength, 4),
        topic=round(min(topic_value, 1.0), 4),
        novelty=novelty, time=round(time_value, 4), cost=round(cost_value, 4),
        uncertainty=round(uncertainty, 4),
        goal_ids=sorted(g for g, m in matches.items() if m.value > 0),
        facts=facts, path=path, notes=notes,
    )
    return candidate, event, presence


def event_candidate(world: World, event: Event) -> Candidate:
    goals = world.ctx.goals
    event_topics = topic_set(event.topics)
    coverage = {
        g.id: (len(event_topics & topic_set(g.topics)) / len(topic_set(g.topics)))
        if topic_set(g.topics) else 0.0
        for g in goals
    }
    confirmed: set[str] = set()
    probable: set[str] = set()
    per_goal_people: dict[str, float] = {g.id: 0.0 for g in goals}
    facts: list[str] = []
    for person in sorted(world.ctx.people, key=lambda p: p.id):
        if person.id in world.met or not world.is_target(person.id):
            continue
        presence, why = world.presence(person, event)
        if presence == "unknown":
            continue
        (confirmed if presence == "confirmed" else probable).add(person.id)
        facts.append(f"target {person.name} {presence}: {why}")
        for goal_id, match in world.matches[person.id].items():
            if match.role > 0:
                per_goal_people[goal_id] += 2.0 if presence == "confirmed" else 1.0

    goal_value = sum(
        world.weights[g.id] * (0.5 * coverage[g.id] + 0.5 * min(per_goal_people[g.id] / 2.0, 1.0))
        for g in goals
    )
    people_value = min((2 * len(confirmed) + len(probable)) / 4.0, 1.0)
    topic_value = sum(world.weights[g.id] * coverage[g.id] for g in goals)
    companies = {world.people[p].company_id for p in confirmed | probable if world.people[p].company_id}
    novelty = (len(companies - world.met_companies) / len(companies)) if companies else 0.0

    notes: dict[str, str] = {"P": f"{len(confirmed)} confirmed, {len(probable)} probable targets"}
    minutes = duration_min(event)
    travel = estimate(world.anchor, event.venue)
    if minutes is None:
        time_value, notes["T"] = 0.0, "event time unknown"
    else:
        time_value = min((minutes + travel.minutes) / TIME_NORM_MIN, 1.0)
        notes["T"] = f"{minutes} min + {travel.minutes} min travel from anchor ({travel.method})"
    cost = known_cost(event)
    if cost is None:
        cost_value, notes["C"] = 0.0, "price unknown"
    else:
        cost_value = float(min(cost / COST_NORM_USD, Decimal(1)))

    relation_unc = {
        "official": 0.0, "confirmed_side_event": 0.0,
        "candidate": 1.0 - (event.relation_score if event.relation_score is not None else 0.5),
    }.get(event.conference_relation, 1.0)
    time_unc = 0.0 if (event.start_at and event.end_at) else 1.0
    uncertainty = (relation_unc + time_unc + venue_uncertainty(event.venue)
                   + evidence_uncertainty(event.evidence)) / 4

    goal_keys = {t for g in goals for t in topic_set(g.topics)}
    shared = [t for t in event.topics if topic_set([t]) & goal_keys]
    facts.insert(0, f"'{event.title}' relation {event.conference_relation}"
                    f"{', topics ' + ', '.join(shared) if shared else ''} ({cite(event.evidence)})")
    path = [{"source": f"Event:{event.id}", "type": "ABOUT", "target": f"Topic:{t}",
             "evidence": cite(event.evidence)} for t in shared]
    path += [{"source": f"Person:{p}", "type": "PRESENT_AT", "target": f"Event:{event.id}",
              "presence": "confirmed" if p in confirmed else "probable"}
             for p in sorted(confirmed | probable)]
    return Candidate(
        kind="event", id=event.id,
        goal=round(min(goal_value, 1.0), 4), people=round(people_value, 4),
        topic=round(min(topic_value, 1.0), 4), novelty=round(novelty, 4),
        time=round(time_value, 4), cost=round(cost_value, 4),
        uncertainty=round(min(uncertainty, 1.0), 4),
        goal_ids=sorted(g for g in coverage if coverage[g] > 0 or per_goal_people[g] > 0),
        facts=facts, path=path, notes=notes,
    )
