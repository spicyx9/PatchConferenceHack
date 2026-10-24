"""Deterministic demo pipeline: goal matching, plan, anti-FOMO clash, replanning.

This is the offline stand-in used to rehearse and back up the stage demo. It is
not the production planner (windows 09/10 own that); it works only on normalized
``conferge.core.schemas`` objects and never touches the network or the clock.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from conferge.core.schemas import (
    AgentContext,
    AgentResult,
    DataMode,
    Event,
    FlightOffer,
    Goal,
    Lodging,
    Opportunity,
    Person,
)
from conferge.demo.seed import DemoWorld, build_world

INELIGIBLE_STATUSES = {"cancelled", "sold_out", "postponed"}
TOPIC_BONUS = 5.0
ARRIVAL_BUFFER = timedelta(hours=2)
UNREACHABLE_FACTOR = 0.5
FIXTURE_WARNING = "fixture: simulated persona, schedule and attendance; not live data"


def score_person(person: Person, goals: list[Goal]) -> tuple[float, list[str], list[str]]:
    """Return (score 0..100, matched goal ids, matched topics)."""
    total = 0.0
    matched_goals: list[str] = []
    matched_topics: set[str] = set()
    for goal in goals:
        if not set(person.roles) & set(goal.target_roles):
            continue
        overlap = set(person.topics) & set(goal.topics)
        ratio = len(overlap) / len(goal.topics) if goal.topics else 0.0
        total += goal.priority * (0.6 + 0.4 * ratio)
        matched_goals.append(goal.id)
        matched_topics |= overlap
    return round(min(total, 1.0) * 100, 2), matched_goals, sorted(matched_topics)


def _linked_people(event: Event, people: list[Person]) -> list[str]:
    ids = set(event.speaker_ids) | set(event.organizer_ids)
    ids |= {p.id for p in people if event.id in p.event_ids}
    return sorted(ids)


def event_value(event: Event, people: list[Person], scores: dict[str, float],
                goal_topics: set[str]) -> float:
    linked = sum(scores.get(pid, 0.0) for pid in _linked_people(event, people))
    topical = TOPIC_BONUS * len(set(event.topics) & goal_topics)
    return round(linked + topical, 2) if linked > 0 else 0.0


def _overlaps(a: Event, b: Event) -> bool:
    assert a.start_at and a.end_at and b.start_at and b.end_at
    return a.start_at < b.end_at and b.start_at < a.end_at


def _haversine_km(a: Event, b: Event) -> float | None:
    va, vb = a.venue, b.venue
    if not va or not vb or None in (va.latitude, va.longitude, vb.latitude, vb.longitude):
        return None
    lat1, lng1, lat2, lng2 = map(math.radians, (va.latitude, va.longitude, vb.latitude,
                                                 vb.longitude))
    h = (math.sin((lat2 - lat1) / 2) ** 2
         + math.cos(lat1) * math.cos(lat2) * math.sin((lng2 - lng1) / 2) ** 2)
    return round(2 * 6371.0 * math.asin(math.sqrt(h)), 2)


def _schedule(events: list[Event], values: dict[str, float]) -> list[Event]:
    """Weighted interval scheduling; ties broken by event id for determinism."""
    ordered = sorted(events, key=lambda e: (e.end_at, e.start_at, e.id))
    best: list[tuple[float, list[Event]]] = [(0.0, [])]
    for i, event in enumerate(ordered):
        j = i - 1
        while j >= 0 and ordered[j].end_at > event.start_at:
            j -= 1
        take_value = best[j + 1][0] + values[event.id]
        skip = best[i]
        if take_value > skip[0]:
            best.append((take_value, best[j + 1][1] + [event]))
        else:
            best.append(skip)
    return sorted(best[-1][1], key=lambda e: (e.start_at, e.id))


def build_plan(events: list[Event], people: list[Person], goals: list[Goal]) -> dict[str, Any]:
    scores = {p.id: score_person(p, goals)[0] for p in people}
    goal_topics = {t for g in goals for t in g.topics}
    eligible = [
        e for e in events
        if e.status not in INELIGIBLE_STATUSES and e.start_at and e.end_at
    ]
    values = {e.id: event_value(e, people, scores, goal_topics) for e in eligible}
    candidates = [e for e in eligible if values[e.id] > 0]
    plan = _schedule(candidates, values)
    chosen = {e.id for e in plan}
    clashes = []
    for i, a in enumerate(candidates):
        for b in candidates[i + 1:]:
            if not _overlaps(a, b):
                continue
            winner, loser = (a, b) if a.id in chosen else (b, a)
            missed = [pid for pid in _linked_people(loser, people) if scores.get(pid, 0) > 0]
            clashes.append({
                "event_ids": sorted([a.id, b.id]),
                "winner": winner.id,
                "skipped": loser.id,
                "winner_value": values[winner.id],
                "skipped_value": values[loser.id],
                "distance_km": _haversine_km(a, b),
                "missed_people": missed,
                "explanation": (
                    f"{winner.title} scores {values[winner.id]} against {values[loser.id]} "
                    f"for {loser.title}; you miss {len(missed)} goal-matched people."
                ),
            })
    return {
        "events": [
            {
                "id": e.id,
                "title": e.title,
                "start_at": e.start_at.isoformat(),
                "end_at": e.end_at.isoformat(),
                "value": values[e.id],
                "people": [p for p in _linked_people(e, people) if scores.get(p, 0) > 0],
            }
            for e in plan
        ],
        "total_value": round(sum(values[e.id] for e in plan), 2),
        "clashes": clashes,
        "excluded": sorted(e.id for e in events if e.status in INELIGIBLE_STATUSES),
    }


def rank_opportunities(people: list[Person], events: list[Event], goals: list[Goal],
                       plan_event_ids: Iterable[str], limit: int = 10) -> list[Opportunity]:
    plan_ids = list(plan_event_ids)
    events_by_id = {e.id: e for e in events}
    ranked: list[tuple[float, str, Opportunity]] = []
    for person in people:
        score, goal_ids, topics = score_person(person, goals)
        if score <= 0:
            continue
        linked = [eid for eid in person.event_ids if eid in events_by_id]
        linked += [e.id for e in events
                   if person.id in set(e.speaker_ids) | set(e.organizer_ids)
                   and e.id not in linked]
        reachable = [eid for eid in linked
                     if events_by_id[eid].status not in INELIGIBLE_STATUSES]
        lost = [eid for eid in linked if eid not in reachable]
        if lost and not reachable:
            score = round(score * UNREACHABLE_FACTOR, 2)
        in_plan = [eid for eid in plan_ids if eid in reachable]
        event_id = in_plan[0] if in_plan else (reachable[0] if reachable else None)
        event = events_by_id.get(event_id) if event_id else None
        confirmed = person.participation in {"confirmed_speaker", "confirmed_organizer"}
        presence = "confirmed" if confirmed and event else "unknown"
        topic = topics[0] if topics else None
        path: list[dict[str, Any]] = [{"kind": "Goal", "id": goal_ids[0]}]
        if topic:
            path.append({"kind": "Topic", "id": topic, "relation": "ABOUT"})
        path.append({"kind": "Person", "id": person.id, "relation": "SERVES_GOAL"})
        if event:
            rel = "SPEAKS_AT" if person.id in event.speaker_ids else "HOSTS"
            path.append({"kind": "Event", "id": event.id, "relation": rel})
        where = None
        if event and event.start_at:
            room = f", {event.room}" if event.room else ""
            where = f"{event.title}{room}, {event.start_at.isoformat()}"
        warnings = [FIXTURE_WARNING]
        warnings += [f"event {eid} is {events_by_id[eid].status}" for eid in lost]
        opp = Opportunity(
            id=f"opp-{person.id}",
            title=f"Meet {person.name} ({person.title})",
            goal_ids=goal_ids,
            event_id=event_id,
            person_ids=[person.id],
            company_ids=[person.company_id] if person.company_id else [],
            score=score,
            rationale=(
                f"Matches {', '.join(goal_ids)}"
                + (f" on {', '.join(topics)}" if topics else "")
                + (f"; reachable at {event.title}" if event else "; no reachable event")
            ),
            path=path,
            where=where,
            opener=(f"Ask about their work on {topic}." if topic else None),
            presence=presence,
            evidence=person.evidence,
            warnings=warnings,
        )
        ranked.append((-score, person.id, opp))
    ranked.sort(key=lambda item: (item[0], item[1]))
    return [opp for _, _, opp in ranked[:limit]]


def pick_travel(flights: list[FlightOffer], lodging: list[Lodging], plan: dict[str, Any],
                budget: Decimal) -> dict[str, Any]:
    first_start = (datetime.fromisoformat(plan["events"][0]["start_at"])
                   if plan["events"] else None)

    def arrival(offer: FlightOffer) -> datetime | None:
        return offer.slices[0].segments[-1].arrival_at

    in_time = [f for f in flights if f.total_price is not None and arrival(f)
               and (first_start is None or arrival(f) + ARRIVAL_BUFFER <= first_start)]
    rejected = sorted(f.id for f in flights if f not in in_time)
    flight = min(in_time, key=lambda f: (Decimal(f.total_price), f.id)) if in_time else None
    flight_cost = Decimal(flight.total_price) if flight else Decimal("0")
    affordable = [s for s in lodging if s.total_price is not None
                  and flight_cost + s.total_price <= budget]
    stay = min(affordable, key=lambda s: (s.distance_to_venue_m or 10**9, s.id), default=None)
    total = flight_cost + (stay.total_price if stay and stay.total_price else Decimal("0"))
    proactive = None
    if flight and plan["events"]:
        first = plan["events"][0]
        proactive = (f"Arrive {arrival(flight).date().isoformat()} to make "
                     f"{first['title']} at {first['start_at']}.")
    return {
        "flight_id": flight.id if flight else None,
        "flight_price_status": flight.price_status if flight else None,
        "rejected_flights": rejected,
        "lodging_id": stay.id if stay else None,
        "lodging_price_status": stay.price_status if stay else None,
        "simulated_total_usd": str(total),
        "budget_usd": str(budget),
        "proactive_suggestion": proactive,
        "label": "fixture: simulated fares and room totals, not live prices",
    }


def plan_diff(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    old = [e["id"] for e in before["events"]]
    new = [e["id"] for e in after["events"]]
    return {
        "removed": [e for e in old if e not in new],
        "added": [e for e in new if e not in old],
        "kept": [e for e in new if e in old],
        "value_before": before["total_value"],
        "value_after": after["total_value"],
    }


def apply_change(events: list[Event], change: dict[str, Any]) -> list[Event]:
    if change["type"] not in {"cancelled", "sold_out"}:
        raise ValueError(f"unsupported demo change: {change['type']}")
    ids = {e.id for e in events}
    if change["event_id"] not in ids:
        raise ValueError(f"unknown event: {change['event_id']}")
    return [
        e.model_copy(update={"status": change["type"]}) if e.id == change["event_id"] else e
        for e in events
    ]


DEFAULT_CHANGE = {
    "id": "scenario-cancel-clash-winner",
    "type": "cancelled",
    "event_id": "evt-side-agents-after-hours",
    "label": "fixture: simulated cancellation for the live-replanning demo",
}


def replay(world: DemoWorld | None = None, change: dict[str, Any] | None = None) -> dict[str, Any]:
    """Run the whole scripted journey; pure function of its inputs."""
    w = world or build_world()
    chg = change or DEFAULT_CHANGE
    plan = build_plan(w.events, w.people, w.goals)
    opps = rank_opportunities(w.people, w.events, w.goals, [e["id"] for e in plan["events"]])
    travel = pick_travel(w.flights, w.lodging, plan, w.user.budget_usd)
    changed_events = apply_change(w.events, chg)
    replan = build_plan(changed_events, w.people, w.goals)
    replan_opps = rank_opportunities(w.people, changed_events, w.goals,
                                     [e["id"] for e in replan["events"]])
    return {
        "source_mode": "fixture",
        "conference_id": w.conference.id,
        "discovery": {
            "events": len(w.events),
            "people": len(w.people),
            "companies": len(w.companies),
            "lodging": len(w.lodging),
            "flights": len(w.flights),
            "source_mode": "fixture",
        },
        "goals": [{"id": g.id, "priority": g.priority} for g in w.goals],
        "top_people": [
            {"id": o.person_ids[0], "score": o.score, "event_id": o.event_id,
             "presence": o.presence, "path": o.path}
            for o in opps
        ],
        "plan": plan,
        "travel": travel,
        "change": chg,
        "replan": replan,
        "diff": plan_diff(plan, replan),
        "top_people_after": [o.person_ids[0] for o in replan_opps],
    }


class DemoPlannerAgent:
    """Implements the ``Agent`` protocol over normalized context only."""

    name = "demo-planner"

    async def run(self, ctx: AgentContext) -> AgentResult:
        mode: DataMode = ctx.data_mode
        if not ctx.events or not ctx.goals:
            return AgentResult(agent=self.name, source_mode=mode, status="failed",
                               errors=["demo planner needs events and goals"])
        events = ctx.events
        for change in ctx.constraints.get("changes", []):
            events = apply_change(events, change)
        plan = build_plan(events, ctx.people, ctx.goals)
        opps = rank_opportunities(ctx.people, events, ctx.goals,
                                  [e["id"] for e in plan["events"]])
        explanations = [c["explanation"] for c in plan["clashes"]]
        if mode != "live":
            explanations.append(f"data_mode={mode}: results are not live observations")
        return AgentResult(
            agent=self.name,
            source_mode=mode,
            status="ok",
            opportunities=opps,
            decisions=[{"kind": "plan", **plan}],
            explanations=explanations,
        )
