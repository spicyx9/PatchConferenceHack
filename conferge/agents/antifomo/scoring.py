"""Opportunity utility for events (docs/knowledge/10-agents-planning.md).

U(o) = wg G + wp P + ws S + wn N - wt T - wc C - wr R, scaled to 0..100.
Presence is evidence based: a target person is *confirmed* at an event only when
listed in its ``speaker_ids`` / ``organizer_ids`` (or an explicit replanning
override); *probable* only with a ``public_attendee_listing`` participation and
the event in ``event_ids``. A public speaker elsewhere is never presence here.
When the planner (window 09) already scored an event through an ``Opportunity``
with ``event_id``, that score is used instead and labelled as such.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from decimal import Decimal

from conferge.agents.antifomo.models import Candidate
from conferge.core.schemas import Event, Goal, Opportunity, Person

WEIGHTS = {"G": 0.35, "P": 0.25, "S": 0.15, "N": 0.10, "T": 0.07, "C": 0.04, "R": 0.04}
_MAX_POSITIVE = WEIGHTS["G"] + WEIGHTS["P"] + WEIGHTS["S"] + WEIGHTS["N"]

PresenceOverrides = Mapping[str, Mapping[str, str]]  # event_id -> person_id -> confirmed|probable


def _low(values: Iterable[str]) -> set[str]:
    return {v.strip().lower() for v in values if v and v.strip()}


def event_cost_usd(event: Event) -> Decimal | None:
    """Known entry cost in USD, or None. Unknown is never turned into zero."""
    if event.is_free is True:
        return Decimal("0")
    if event.price_min is not None and event.currency == "USD":
        return Decimal(event.price_min)
    return None


def target_people(
    event: Event, people: list[Person], goals: list[Goal],
    overrides: PresenceOverrides | None = None, met: set[str] | None = None,
) -> tuple[list[Person], list[Person]]:
    roles = _low(r for g in goals for r in g.target_roles)
    met = met or set()
    hosts = set(event.speaker_ids) | set(event.organizer_ids)
    forced = (overrides or {}).get(event.id, {})
    confirmed: list[Person] = []
    probable: list[Person] = []
    for person in sorted(people, key=lambda p: p.id):
        if person.id in met or not (_low(person.roles) & roles):
            continue
        status = forced.get(person.id)
        if status == "confirmed" or (status is None and person.id in hosts):
            confirmed.append(person)
        elif status == "probable" or (
            status is None and event.id in person.event_ids
            and person.participation == "public_attendee_listing"
        ):
            probable.append(person)
    return confirmed, probable


def score_event(
    event: Event, goals: list[Goal], people: list[Person],
    overrides: PresenceOverrides | None = None, met: set[str] | None = None,
) -> Candidate:
    ev_topics = _low(event.topics)
    all_goal_topics = _low(t for g in goals for t in g.topics)
    roles_by_goal = {g.id: _low(g.target_roles) for g in goals}
    confirmed, probable = target_people(event, people, goals, overrides, met)

    total_priority = sum(g.priority for g in goals) or 1.0
    g_score = 0.0
    goal_ids: list[str] = []
    for goal in goals:
        gt = _low(goal.topics)
        overlap = len(ev_topics & gt) / len(gt) if gt else 0.0
        people_hit = any(_low(p.roles) & roles_by_goal[goal.id] for p in confirmed + probable)
        if overlap or people_hit:
            goal_ids.append(goal.id)
        g_score += goal.priority * max(overlap, 1.0 if people_hit else 0.0)
    g_score /= total_priority

    p_score = min(1.0, (2 * len(confirmed) + len(probable)) / 6)
    s_score = len(ev_topics & all_goal_topics) / len(ev_topics) if ev_topics else 0.0
    companies = sorted({p.company_id for p in confirmed + probable if p.company_id})
    n_score = min(1.0, len(companies) / 3)

    reasons: list[str] = []
    r_score = 0.0
    if event.start_at and event.end_at:
        t_score = min(1.0, (event.end_at - event.start_at).total_seconds() / 3600 / 4)
    else:
        t_score = 0.5
    cost = event_cost_usd(event)
    c_score = min(1.0, float(cost) / 100) if cost is not None else 0.0
    if cost is None:
        r_score += 0.1
        reasons.append("entry price unknown")
    if event.conference_relation == "candidate":
        r_score += 0.3
    elif event.conference_relation in {"unknown", "unrelated"}:
        r_score += 0.4
    if event.registration_url is None:
        r_score += 0.2
    venue = event.venue
    if venue is None or venue.coordinate_precision not in {"exact", "approximate"}:
        r_score += 0.2
        reasons.append("venue location imprecise")
    r_score = min(1.0, r_score)

    raw = (
        WEIGHTS["G"] * g_score + WEIGHTS["P"] * p_score + WEIGHTS["S"] * s_score
        + WEIGHTS["N"] * n_score - WEIGHTS["T"] * t_score - WEIGHTS["C"] * c_score
        - WEIGHTS["R"] * r_score
    )
    utility = round(100 * max(0.0, raw) / _MAX_POSITIVE, 2)
    head: list[str] = []
    if confirmed:
        head.append("confirmed targets: " + ", ".join(p.name for p in confirmed))
    if probable:
        head.append("probable targets: " + ", ".join(p.name for p in probable))
    reasons = head + reasons
    if ev_topics & all_goal_topics:
        reasons.append("goal topics: " + ", ".join(sorted(ev_topics & all_goal_topics)))
    return Candidate(
        event=event, utility=min(100.0, utility),
        breakdown={k: round(v, 4) for k, v in {
            "G": g_score, "P": p_score, "S": s_score, "N": n_score,
            "T": t_score, "C": c_score, "R": r_score,
        }.items()},
        goal_ids=goal_ids,
        targets_confirmed=[p.id for p in confirmed],
        targets_probable=[p.id for p in probable],
        target_companies=companies,
        reasons=reasons,
        cost_usd=cost,
    )


def build_candidates(
    events: list[Event], goals: list[Goal], people: list[Person],
    opportunities: list[Opportunity] | None = None,
    overrides: PresenceOverrides | None = None, met: set[str] | None = None,
) -> list[Candidate]:
    planner_scores: dict[str, float] = {}
    for opp in opportunities or []:
        if opp.event_id:
            planner_scores[opp.event_id] = max(planner_scores.get(opp.event_id, 0.0), opp.score)
    out: list[Candidate] = []
    for event in sorted(events, key=lambda e: e.id):
        cand = score_event(event, goals, people, overrides, met)
        if event.id in planner_scores:
            cand = cand.model_copy(update={
                "utility": planner_scores[event.id],
                "score_source": "planner_opportunity",
                "breakdown": {**cand.breakdown, "planner_score": planner_scores[event.id]},
            })
        out.append(cand)
    return out
