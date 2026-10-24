"""Deterministic API-side fallbacks used until the real agents are merged.

These functions never invent data: they only rank, filter and arrange what
the dataset already holds. Results are tagged ``computed_by="api-fallback"``
so the UI can tell them apart from planner/anti-FOMO agent output.
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections import deque
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from conferge.api.data import DemoData
from conferge.core.schemas import Event, Goal, Opportunity, Person, SourceEvidence

FALLBACK = "api-fallback"

_GOAL_RULES: list[tuple[str, re.Pattern[str], list[str], list[str], str]] = [
    (
        "goal-seed-investors",
        re.compile(r"\b(investisseurs?|investors?|vcs?|seed|business angels?)\b"),
        ["investor"], ["AI agents", "developer tools"], "Meet seed investors",
    ),
    (
        "goal-agent-founders",
        re.compile(r"\b(fondateurs?|founders?)\b[^.,;]*\bagents?\b|\bagents?\b[^.,;]*\b(fondateurs?|founders?)\b"),
        ["founder"], ["AI agents", "MCP"], "Meet AI agent founders",
    ),
    (
        "goal-copilot-pm",
        re.compile(r"\b(pms?|product managers?)\b[^.,;]*\bcopilot\b|\bcopilot\b[^.,;]*\b(pms?|product managers?)\b"),
        ["pm"], ["Copilot"], "Meet Copilot product managers",
    ),
    (
        "goal-engineers",
        re.compile(r"\b(ingenieurs?|engineers?|developpeurs?|developers?)\b"),
        ["engineer"], ["AI agents", "developer tools"], "Meet engineers",
    ),
]
# Weights by order of mention; the demo goal yields 0.45 / 0.35 / 0.20.
_WEIGHTS = [0.45, 0.35, 0.20, 0.10]

_PRESENCE_FACTOR = {
    "confirmed_speaker": 1.0,
    "confirmed_organizer": 1.0,
    "public_attendee_listing": 0.8,
    "relevant_candidate": 0.5,
    "unknown": 0.25,
}


def _fold(text: str) -> str:
    norm = unicodedata.normalize("NFKD", text)
    return "".join(c for c in norm if not unicodedata.combining(c)).lower()


def parse_goals(text: str) -> list[Goal]:
    """Keyword goal extraction; the planner agent replaces this when present."""
    folded = _fold(text)
    found: list[tuple[int, tuple[str, list[str], list[str], str]]] = []
    for goal_id, pattern, roles, topics, label in _GOAL_RULES:
        match = pattern.search(folded)
        if match:
            found.append((match.start(), (goal_id, roles, topics, label)))
    found.sort(key=lambda item: item[0])
    picked = found[: len(_WEIGHTS)]
    total = sum(_WEIGHTS[: len(picked)]) or 1.0
    goals = []
    for index, (_, (goal_id, roles, topics, label)) in enumerate(picked):
        goals.append(Goal(
            id=goal_id, description=label, priority=round(_WEIGHTS[index] / total, 2),
            target_roles=roles, topics=topics, tags=["parsed:" + FALLBACK],
        ))
    return goals


def _event_label(event: Event) -> str:
    when = event.start_at.strftime("%a %d %b %H:%M") if event.start_at else "time unknown"
    room = f", {event.room}" if event.room else ""
    venue = event.venue.name if event.venue and event.venue.name else "venue unknown"
    return f"{event.title} ({when}, {venue}{room})"


def person_goal_match(person: Person, goal: Goal) -> float:
    role_hit = 1.0 if set(person.roles) & set(goal.target_roles) else 0.0
    topic_hit = 0.25 if set(person.topics) & set(goal.topics) else 0.0
    return min(role_hit + topic_hit, 1.0) if role_hit else topic_hit


def rank_people(
    data: DemoData, goals: list[Goal], met: dict[str, str] | None = None
) -> list[Opportunity]:
    """Score = 100 * sum(goal weight * match) * presence factor; met people sink."""
    met = met or {}
    opportunities: list[Opportunity] = []
    for person in data.people:
        matches = {g.id: person_goal_match(person, g) for g in goals}
        raw = sum(g.priority * matches[g.id] for g in goals)
        if raw <= 0:
            continue
        factor = _PRESENCE_FACTOR.get(person.participation, 0.25)
        score = 100.0 * raw * factor
        warnings: list[str] = []
        if person.id in met:
            score *= 0.2
            warnings.append("already met: ranked down")
        best_goal = max(goals, key=lambda g: g.priority * matches[g.id])
        events = [e for e in (data.event(i) for i in person.event_ids) if e is not None]
        event = events[0] if events else None
        if person.participation in {"confirmed_speaker", "confirmed_organizer"} and event:
            presence = "confirmed"
        elif person.participation in {"public_attendee_listing", "relevant_candidate"} and event:
            presence = "probable"
        else:
            presence = "unknown"
        shared = sorted(set(person.topics) & set(best_goal.topics))
        company = data.company(person.company_id)
        rationale = (
            f"{best_goal.description} (weight {best_goal.priority}): "
            f"{', '.join(person.roles) or 'role unknown'}"
            + (f" at {company.name}" if company else "")
            + (f", shared topics {', '.join(shared)}" if shared else "")
            + f"; participation {person.participation}."
        )
        topic = shared[0] if shared else (person.topics[0] if person.topics else "their work")
        opportunities.append(Opportunity(
            id=f"opp-{person.id}",
            title=person.name,
            goal_ids=[g.id for g in goals if matches[g.id] > 0],
            event_id=event.id if event else None,
            person_ids=[person.id],
            company_ids=[person.company_id] if person.company_id else [],
            score=round(min(score, 100.0), 1),
            rationale=rationale,
            path=person_path(data, goals, person.id),
            where=_event_label(event) if event else None,
            opener=f"Ask {person.name.split(' ')[0]} how they approach {topic} today.",
            presence=presence,
            evidence=list(person.evidence),
            warnings=warnings,
        ))
    opportunities.sort(key=lambda o: (-o.score, o.id))
    return opportunities


def _overlaps(a: Event, b: Event) -> bool:
    if not (a.start_at and a.end_at and b.start_at and b.end_at):
        return False
    return a.start_at < b.end_at and b.start_at < a.end_at


def event_scores(
    data: DemoData, goals: list[Goal], opportunities: list[Opportunity]
) -> dict[str, float]:
    by_person = {pid: o.score for o in opportunities for pid in o.person_ids}
    goal_topics = {t for g in goals for t in g.topics}
    scores: dict[str, float] = {}
    for event in data.events:
        people_ids = set(event.speaker_ids) | set(event.organizer_ids)
        people_ids |= {p.id for p in data.people if event.id in p.event_ids}
        people_value = sum(by_person.get(pid, 0.0) for pid in people_ids)
        topic_value = 5.0 * len(goal_topics & set(event.topics))
        scores[event.id] = round(min(people_value + topic_value, 100.0), 1)
    return scores


def _local_day(event: Event) -> date | None:
    return event.start_at.date() if event.start_at else None


def build_plan(
    data: DemoData,
    goals: list[Goal],
    opportunities: list[Opportunity],
    *,
    skipped: set[str] | None = None,
    attended: set[str] | None = None,
) -> dict[str, Any]:
    """Greedy reverse plan: per day keep the best non-overlapping events.

    Overlapping candidates become anti-FOMO conflicts with a verdict and the
    people the user misses by choosing the winner.
    """
    skipped = skipped or set()
    attended = attended or set()
    scores = event_scores(data, goals, opportunities)
    opp_by_person = {pid: o for o in opportunities for pid in o.person_ids}
    available = [
        e for e in data.events
        if e.start_at and e.status not in {"cancelled", "sold_out"} and e.id not in skipped
    ]
    excluded = [
        {"event_id": e.id, "title": e.title, "reason": e.status if e.status in {"cancelled", "sold_out"} else "skipped"}
        for e in data.events
        if e.status in {"cancelled", "sold_out"} or e.id in skipped
    ]
    unscheduled = [{"event_id": e.id, "title": e.title} for e in data.events if not e.start_at]
    days: dict[str, list[Event]] = {}
    for event in available:
        days.setdefault(str(_local_day(event)), []).append(event)

    plan_days = []
    conflicts = []
    for day in sorted(days):
        candidates = sorted(days[day], key=lambda e: (-(scores.get(e.id, 0) + (1000 if e.id in attended else 0)), e.id))
        chosen: list[Event] = []
        for event in candidates:
            clash = next((c for c in chosen if _overlaps(c, event)), None)
            if clash is None:
                chosen.append(event)
                continue
            missed = [
                {"person_id": pid, "name": opp_by_person[pid].title, "score": opp_by_person[pid].score}
                for pid in _event_people(data, event) if pid in opp_by_person
            ]
            conflicts.append({
                "day": day,
                "winner": {"event_id": clash.id, "title": clash.title, "score": scores.get(clash.id, 0)},
                "loser": {"event_id": event.id, "title": event.title, "score": scores.get(event.id, 0)},
                "verdict": (
                    f"Go to '{clash.title}' (score {scores.get(clash.id, 0)}) rather than "
                    f"'{event.title}' (score {scores.get(event.id, 0)})."
                ),
                "what_you_miss": missed,
                "computed_by": FALLBACK,
            })
        chosen.sort(key=lambda e: e.start_at)  # type: ignore[arg-type, return-value]
        plan_days.append({
            "day": day,
            "items": [
                {
                    "event_id": e.id, "title": e.title, "event_type": e.event_type,
                    "start_at": e.start_at.isoformat() if e.start_at else None,
                    "end_at": e.end_at.isoformat() if e.end_at else None,
                    "timezone": e.timezone,
                    "venue": e.venue.name if e.venue else None,
                    "room": e.room, "status": e.status, "score": scores.get(e.id, 0),
                    "attended": e.id in attended,
                    "people": [
                        {"person_id": pid, "name": opp_by_person[pid].title}
                        for pid in _event_people(data, e) if pid in opp_by_person
                    ],
                    "source_mode": _mode_of(e.evidence),
                }
                for e in chosen
            ],
        })
    return {
        "days": plan_days, "conflicts": conflicts, "excluded": excluded,
        "unscheduled": unscheduled, "computed_by": FALLBACK,
    }


def _event_people(data: DemoData, event: Event) -> list[str]:
    ids = list(dict.fromkeys(event.speaker_ids + event.organizer_ids))
    ids += [p.id for p in data.people if event.id in p.event_ids and p.id not in ids]
    return ids


def _mode_of(evidence: list[SourceEvidence]) -> str:
    modes = {e.source_mode for e in evidence}
    if not modes:
        return "unknown"
    return modes.pop() if len(modes) == 1 else "mixed"


def plan_diff(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    def items(plan: dict[str, Any]) -> dict[str, dict[str, Any]]:
        return {i["event_id"]: i for d in plan["days"] for i in d["items"]}

    old, new = items(before), items(after)
    changed = [
        {"event_id": k, "before": {"start_at": old[k]["start_at"], "status": old[k]["status"]},
         "after": {"start_at": new[k]["start_at"], "status": new[k]["status"]}}
        for k in old.keys() & new.keys()
        if (old[k]["start_at"], old[k]["status"]) != (new[k]["start_at"], new[k]["status"])
    ]
    return {
        "added": [{"event_id": k, "title": new[k]["title"]} for k in sorted(new.keys() - old.keys())],
        "removed": [{"event_id": k, "title": old[k]["title"]} for k in sorted(old.keys() - new.keys())],
        "changed": sorted(changed, key=lambda c: c["event_id"]),
    }


# Graph

def build_graph(
    data: DemoData, goals: list[Goal], met: dict[str, str] | None = None, user_id: str = "demo-user"
) -> dict[str, Any]:
    """UI graph from the dataset; each edge carries source, confidence, observed_at."""
    met = met or {}
    nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, Any]] = []

    def node(nid: str, kind: str, label: str, mode: str) -> None:
        nodes.setdefault(nid, {"id": nid, "type": kind, "label": label, "source_mode": mode})

    def edge(src: str, rel: str, dst: str, source: str, confidence: float, observed: Any) -> None:
        edges.append({
            "id": f"{src}|{rel}|{dst}", "source": src, "target": dst, "type": rel,
            "evidence_source": source, "confidence": confidence,
            "observed_at": observed.isoformat() if observed else None,
        })

    collected = data.domains["events"].collected_at
    node(f"user:{user_id}", "User", "You", "fixture")
    conf = data.conference
    node(conf.id, "Conference", conf.name, _mode_of(conf.evidence))
    for goal in goals:
        node(goal.id, "Goal", f"{goal.description} ({goal.priority})", "fixture")
        edge(f"user:{user_id}", "HAS_GOAL", goal.id, FALLBACK, 1.0, None)
        for topic in goal.topics:
            node(f"topic:{topic}", "Topic", topic, "fixture")
            edge(goal.id, "ABOUT", f"topic:{topic}", FALLBACK, 1.0, None)
        for role in goal.target_roles:
            for person in data.people:
                if role in person.roles:
                    edge(goal.id, "SERVES_GOAL", person.id, FALLBACK, 0.9, None)
    for event in data.events:
        mode = _mode_of(event.evidence)
        node(event.id, "Event", event.title, mode)
        provider = event.evidence[0].provider if event.evidence else "unknown"
        edge(event.id, "PART_OF", conf.id, provider, event.relation_score or 0.5, collected)
        for topic in event.topics:
            node(f"topic:{topic}", "Topic", topic, "fixture")
            edge(event.id, "ABOUT", f"topic:{topic}", provider, 0.8, collected)
    for company in data.companies:
        node(company.id, "Company", company.name, _mode_of(company.evidence))
    for person in data.people:
        node(person.id, "Person", person.name, _mode_of(person.evidence))
        provider = person.evidence[0].provider if person.evidence else "unknown"
        if person.company_id and person.company_id in nodes:
            edge(person.id, "WORKS_AT", person.company_id, provider, 0.9, collected)
        for topic in person.topics:
            node(f"topic:{topic}", "Topic", topic, "fixture")
            edge(person.id, "ABOUT", f"topic:{topic}", provider, 0.7, collected)
        for event_id in person.event_ids:
            if event_id not in nodes:
                continue
            rel = {
                "confirmed_speaker": "SPEAKS_AT", "confirmed_organizer": "HOSTS",
                "public_attendee_listing": "ATTENDS_CONFIRMED",
            }.get(person.participation, "CONNECTED_TO")
            confidence = 0.95 if rel != "CONNECTED_TO" else 0.4
            edge(person.id, rel, event_id, provider, confidence, collected)
        if person.id in met:
            edge(f"user:{user_id}", "MET", person.id, "user", 1.0, None)
    return {"nodes": list(nodes.values()), "edges": edges}


def shortest_path(graph: dict[str, Any], start: str, goal: str) -> list[dict[str, Any]]:
    """Undirected BFS; returns alternating node/edge steps or []."""
    adjacency: dict[str, list[tuple[str, dict[str, Any]]]] = {}
    for e in graph["edges"]:
        adjacency.setdefault(e["source"], []).append((e["target"], e))
        adjacency.setdefault(e["target"], []).append((e["source"], e))
    previous: dict[str, tuple[str, dict[str, Any]] | None] = {start: None}
    queue = deque([start])
    while queue:
        current = queue.popleft()
        if current == goal:
            break
        for nxt, e in sorted(adjacency.get(current, []), key=lambda x: x[0]):
            if nxt not in previous:
                previous[nxt] = (current, e)
                queue.append(nxt)
    if goal not in previous:
        return []
    nodes = {n["id"]: n for n in graph["nodes"]}
    steps: list[dict[str, Any]] = []
    cursor: str | None = goal
    while cursor is not None:
        steps.append({"node": nodes.get(cursor, {"id": cursor})})
        link = previous[cursor]
        if link is None:
            break
        steps.append({"edge": link[1]})
        cursor = link[0]
    return list(reversed(steps))


def person_path(data: DemoData, goals: list[Goal], person_id: str) -> list[dict[str, Any]]:
    """Explainable chain user -> goal -> person, preferring goal-role links."""
    graph = build_graph(data, goals)
    steps = shortest_path(graph, "user:demo-user", person_id)
    return [
        {"node": s["node"]["id"], "type": s["node"].get("type")} if "node" in s
        else {"edge": s["edge"]["type"]}
        for s in steps
    ]


# Travel

def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> int:
    r = 6_371_000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return int(round(2 * r * math.asin(math.sqrt(a))))


def stays_view(data: DemoData) -> list[dict[str, Any]]:
    conf = data.conference
    out = []
    for stay in data.stays:
        item = stay.model_dump(mode="json")
        distance = stay.distance_to_venue_m
        computed = False
        if distance is None and stay.venue and stay.venue.latitude is not None and conf.latitude is not None:
            distance = haversine_m(stay.venue.latitude, stay.venue.longitude, conf.latitude, conf.longitude)  # type: ignore[arg-type]
            computed = True
        item["distance_to_venue_m"] = distance
        item["distance_is_straight_line_estimate"] = computed
        item["source_mode"] = _mode_of(stay.evidence)
        out.append(item)
    return out


def travel_view(
    data: DemoData, plan: dict[str, Any], accepted: set[str]
) -> dict[str, Any]:
    user = data.user
    legs: list[dict[str, Any]] = []
    for flight in data.flights:
        for index, sl in enumerate(flight.slices):
            first, last = sl.segments[0], sl.segments[-1]
            legs.append({
                "kind": "flight", "offer_id": flight.id,
                "date": user["depart_date"] if index == 0 else user["return_date"],
                "from": first.origin_iata, "to": last.destination_iata,
                "departure_at": first.departure_at.isoformat() if first.departure_at else None,
                "arrival_at": last.arrival_at.isoformat() if last.arrival_at else None,
                "carrier": first.marketing_carrier, "price_status": flight.price_status,
                "source_mode": _mode_of(flight.evidence),
            })
    stays = stays_view(data)
    if stays:
        legs.insert(1 if legs else 0, {
            "kind": "stay", "stay_id": stays[0]["id"], "name": stays[0]["name"],
            "check_in": stays[0]["check_in"], "check_out": stays[0]["check_out"],
            "price_status": stays[0]["price_status"], "source_mode": stays[0]["source_mode"],
        })
    proposals = []
    arrival_day = user["depart_date"]
    for day in plan["days"]:
        if day["day"] != arrival_day or not day["items"]:
            continue
        first = day["items"][0]
        pid = f"prop-arrive-for-{first['event_id']}"
        proposals.append({
            "id": pid,
            "text": (
                f"You land on {arrival_day}: pick a flight arriving before "
                f"{first['start_at']} to make '{first['title']}'."
            ),
            "reason": f"event score {first['score']} on your arrival day",
            "accepted": pid in accepted,
            "computed_by": FALLBACK,
        })
    budget = Decimal(str(user["budget_usd"]))
    flight_total = _sum_known([f.total_price for f in data.flights[:1]])
    stay_total = _sum_known([s.total_price for s in data.stays[:1]])
    return {
        "itinerary": legs,
        "proposals": proposals,
        "budget": {
            "budget_usd": str(budget),
            "flights_usd": flight_total, "lodging_usd": stay_total,
            "remaining_usd": (
                str(budget - Decimal(flight_total) - Decimal(stay_total))
                if flight_total is not None and stay_total is not None else None
            ),
            "note": "null means the price was not collected; nothing is estimated",
        },
    }


def _sum_known(values: list[Any]) -> str | None:
    if not values or any(v is None for v in values):
        return None
    return str(sum(Decimal(str(v)) for v in values))


def travel_map(data: DemoData, plan: dict[str, Any]) -> dict[str, Any]:
    conf = data.conference
    markers = []
    if conf.latitude is not None and conf.longitude is not None:
        markers.append({"id": conf.id, "kind": "conference", "label": conf.venue_name or conf.name,
                        "lat": conf.latitude, "lng": conf.longitude, "precision": "approximate"})
    planned = {i["event_id"] for d in plan["days"] for i in d["items"]}
    for event in data.events:
        v = event.venue
        if v and v.latitude is not None and v.longitude is not None:
            markers.append({"id": event.id, "kind": "event", "label": event.title, "lat": v.latitude,
                            "lng": v.longitude, "precision": v.coordinate_precision,
                            "planned": event.id in planned})
    for stay in data.stays:
        v = stay.venue
        if v and v.latitude is not None and v.longitude is not None:
            markers.append({"id": stay.id, "kind": "stay", "label": stay.name, "lat": v.latitude,
                            "lng": v.longitude, "precision": v.coordinate_precision})
    polylines = []
    coords = {m["id"]: (m["lat"], m["lng"]) for m in markers}
    for day in plan["days"]:
        points = [coords[i["event_id"]] for i in day["items"] if i["event_id"] in coords]
        if data.stays and data.stays[0].id in coords:
            home = coords[data.stays[0].id]
            points = [home, *points, home]
        if len(points) >= 2:
            polylines.append({"day": day["day"], "points": [list(p) for p in points],
                              "kind": "straight_line_order_of_visits"})
    return {"markers": markers, "polylines": polylines}


def roi_view(
    data: DemoData, goals: list[Goal], opportunities: list[Opportunity], met: dict[str, str]
) -> dict[str, Any]:
    travel = travel_view(data, {"days": []}, set())
    known = [travel["budget"]["flights_usd"], travel["budget"]["lodging_usd"]]
    spend = _sum_known(known)
    qualified = [
        pid for pid in met
        if (p := data.person(pid)) is not None and any(person_goal_match(p, g) >= 1 for g in goals)
    ]
    return {
        "spend_usd": spend,
        "spend_note": None if spend is not None else "unknown until flight and lodging prices are collected",
        "meetings": len(met),
        "qualified_contacts": len(qualified),
        "opportunities": sum(1 for o in opportunities if o.score >= 30),
        "budget_usd": travel["budget"]["budget_usd"],
    }


TOP_PLAN_EVENT = "top_plan_event"


def top_plan_item(plan: dict[str, Any]) -> dict[str, Any] | None:
    """Highest-scored item of the plan; ties go to the earliest in plan order."""
    items = [i for d in plan["days"] for i in d["items"]]
    return max(items, key=lambda i: i["score"], default=None) if items else None


def resolve_scenario(scenario: dict[str, Any], plan: dict[str, Any]) -> dict[str, Any]:
    """Bind ``{"target": "top_plan_event"}`` changes to the current plan, never to a fixed id."""
    changes = []
    for change in scenario.get("changes", []):
        if change.get("target") == TOP_PLAN_EVENT:
            top = top_plan_item(plan)
            if top is None:
                continue
            change = {"event_id": top["event_id"], "set": change["set"]}
        changes.append(change)
    return {**scenario, "changes": changes}


def explain_replan(before: dict[str, Any], after: dict[str, Any], changed: list[str],
                   data: DemoData) -> list[dict[str, Any]]:
    """Per removed item: the replacement chosen in its slot and why, in plain words."""
    old = {i["event_id"]: (d["day"], i) for d in before["days"] for i in d["items"]}
    new = {i["event_id"]: (d["day"], i) for d in after["days"] for i in d["items"]}
    out = []
    for event_id in sorted(old.keys() - new.keys()):
        day, item = old[event_id]
        event = data.event(event_id)
        added = [i for k, (d, i) in new.items() if k not in old and d == day]
        same_slot = [i for i in added if event and (e := data.event(i["event_id"])) and _overlaps(event, e)]
        replacement = max(same_slot or added, key=lambda i: i["score"], default=None)
        status = event.status if event else "removed"
        cause = (f"'{item['title']}' is now {status}" + (" (simulated change)" if event_id in changed else ""))
        if replacement is None:
            reason = f"{cause}; no other scheduled event fits that day, the slot stays free."
        else:
            slot = "in the same time slot" if replacement in same_slot else "the same day"
            reason = (f"{cause}; '{replacement['title']}' is the best remaining event {slot} "
                      f"(score {replacement['score']} vs {item['score']}).")
        out.append({
            "removed": {"event_id": event_id, "title": item["title"], "start_at": item["start_at"],
                        "score": item["score"], "status": status},
            "replacement": None if replacement is None else {
                "event_id": replacement["event_id"], "title": replacement["title"],
                "start_at": replacement["start_at"], "score": replacement["score"],
                "people": replacement["people"],
            },
            "reason": reason,
        })
    return out


def apply_scenario(data: DemoData, scenario: dict[str, Any]) -> list[str]:
    """Mutate events in place (validated by pydantic); return changed event ids."""
    changed = []
    for change in scenario.get("changes", []):
        event = data.event(change["event_id"])
        if event is None:
            continue
        updated = event.model_copy(update={})
        payload = updated.model_dump()
        for key, value in change["set"].items():
            payload[key] = datetime.fromisoformat(value) if key.endswith("_at") else value
        new_event = Event.model_validate(payload)
        data.events[data.events.index(event)] = new_event
        changed.append(event.id)
    return changed
