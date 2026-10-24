"""Live replanning: typed changes, state update, minimal-change replan and diff.

``apply_change`` returns a new ``PlanningState`` (inputs are never mutated) and,
when a ``GraphStore`` is given, records the change through its MERGE methods
only. ``replan`` re-runs the optimizer with ``original=`` so that unaffected
items stay put. ``diff`` explains what moved and why, in plain text.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from conferge.agents.antifomo.models import Candidate, Constraints, Plan, PlanItem, TimeSlot
from conferge.agents.antifomo.optimizer import optimize
from conferge.agents.antifomo.scoring import build_candidates
from conferge.core.schemas import Event, Goal, Opportunity, Person, SourceMode, Venue
from conferge.core.store import GraphStore

ChangeType = Literal[
    "new_event", "time_change", "sold_out", "cancelled", "venue_change",
    "person_target_available", "meeting_accepted", "meeting_declined", "flight_delay",
    "user_skipped", "new_contact_met",
]
_NEEDS_EVENT = {"time_change", "sold_out", "cancelled", "venue_change",
                "person_target_available", "user_skipped"}


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Change(_Model):
    type: ChangeType
    event_id: str | None = None
    event: Event | None = None
    start_at: AwareDatetime | None = None
    end_at: AwareDatetime | None = None
    venue: Venue | None = None
    person_id: str | None = None
    presence: Literal["confirmed", "probable"] = "probable"
    slot: TimeSlot | None = None
    slot_id: str | None = None
    note: str | None = None
    source_mode: SourceMode = "fixture"
    observed_at: AwareDatetime | None = None


class PlanningState(_Model):
    conference_id: str | None = None
    events: list[Event] = Field(default_factory=list)
    people: list[Person] = Field(default_factory=list)
    goals: list[Goal] = Field(default_factory=list)
    opportunities: list[Opportunity] = Field(default_factory=list)
    constraints: Constraints = Field(default_factory=Constraints)
    presence_overrides: dict[str, dict[str, str]] = Field(default_factory=dict)
    met_person_ids: list[str] = Field(default_factory=list)

    def event(self, event_id: str) -> Event | None:
        return next((e for e in self.events if e.id == event_id), None)

    def candidates(self) -> list[Candidate]:
        return build_candidates(self.events, self.goals, self.people, self.opportunities,
                                self.presence_overrides, set(self.met_person_ids))


class ChangeResult(_Model):
    state: PlanningState
    effects: list[str] = Field(default_factory=list)
    graph_writes: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


def _updated(event: Event, **changes: Any) -> Event:
    """Copy with full re-validation (model_copy would skip validators)."""
    return Event.model_validate({**event.model_dump(), **changes})


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def apply_change(state: PlanningState, change: Change, store: GraphStore | None = None
                 ) -> ChangeResult:
    if change.type in _NEEDS_EVENT:
        if not change.event_id or state.event(change.event_id) is None:
            raise ValueError(f"{change.type} needs a known event_id, got {change.event_id!r}")
    events = list(state.events)
    constraints = state.constraints.model_copy(deep=True)
    overrides = {k: dict(v) for k, v in state.presence_overrides.items()}
    met = list(state.met_person_ids)
    effects: list[str] = []
    graph: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
    stamp = {"last_change": change.type, "change_source_mode": change.source_mode,
             "observed_at": _iso(change.observed_at)}

    def replace(ev: Event) -> None:
        events[:] = [ev if e.id == ev.id else e for e in events]

    target = state.event(change.event_id) if change.event_id else None
    if change.type == "new_event":
        if change.event is None:
            raise ValueError("new_event needs an event")
        if state.event(change.event.id):
            raise ValueError(f"event {change.event.id} already exists")
        events.append(change.event)
        effects.append(f"new event '{change.event.title}'")
        graph.append(("merge_node", ("Event", change.event.id), {
            "title": change.event.title, "status": change.event.status,
            "start_at": _iso(change.event.start_at), "end_at": _iso(change.event.end_at),
            **stamp}))
        if state.conference_id and change.event.conference_relation in {
                "official", "confirmed_side_event"}:
            graph.append(("merge_edge", ("Event", change.event.id, "PART_OF", "Conference",
                                         state.conference_id), {"source": change.source_mode}))
    elif change.type == "time_change":
        assert target is not None
        if change.start_at is None or change.end_at is None:
            raise ValueError("time_change needs start_at and end_at")
        replace(_updated(target, start_at=change.start_at, end_at=change.end_at))
        effects.append(f"'{target.title}' moved to {change.start_at:%a %H:%M}-{change.end_at:%H:%M}")
        graph.append(("merge_node", ("Event", target.id), {
            "start_at": _iso(change.start_at), "end_at": _iso(change.end_at), **stamp}))
    elif change.type in {"sold_out", "cancelled"}:
        assert target is not None
        replace(_updated(target, status=change.type))
        effects.append(f"'{target.title}' is now {change.type.replace('_', ' ')}")
        graph.append(("merge_node", ("Event", target.id), {"status": change.type, **stamp}))
    elif change.type == "venue_change":
        assert target is not None
        if change.venue is None:
            raise ValueError("venue_change needs a venue")
        replace(_updated(target, venue=change.venue.model_dump()))
        effects.append(f"'{target.title}' moved to venue {change.venue.name or 'unknown'}")
        graph.append(("merge_node", ("Event", target.id), {"venue_name": change.venue.name,
                                                            **stamp}))
    elif change.type == "person_target_available":
        assert target is not None
        if not change.person_id:
            raise ValueError("person_target_available needs person_id")
        overrides.setdefault(target.id, {})[change.person_id] = change.presence
        effects.append(f"{change.person_id} is {change.presence} at '{target.title}'")
        if change.presence == "confirmed":
            graph.append(("merge_edge", ("Person", change.person_id, "ATTENDS_CONFIRMED",
                                         "Event", target.id),
                          {"source": change.source_mode, "confidence": 1.0,
                           "observed_at": _iso(change.observed_at)}))
    elif change.type in {"meeting_accepted", "flight_delay"}:
        if change.slot is None:
            raise ValueError(f"{change.type} needs a slot")
        constraints.blocked = [s for s in constraints.blocked if s.id != change.slot.id]
        constraints.blocked.append(change.slot)
        effects.append(f"blocked {change.slot.start:%a %H:%M}-{change.slot.end:%H:%M} "
                       f"for '{change.slot.label}'")
        if change.type == "meeting_accepted":
            graph.append(("merge_node", ("Meeting", change.slot.id), {
                "label": change.slot.label, "status": "accepted",
                "start_at": _iso(change.slot.start), "end_at": _iso(change.slot.end), **stamp}))
            if change.person_id:
                graph.append(("merge_edge", ("Meeting", change.slot.id, "INVOLVES", "Person",
                                             change.person_id), {"source": change.source_mode}))
    elif change.type == "meeting_declined":
        slot_id = change.slot_id or (change.slot.id if change.slot else None)
        if not slot_id:
            raise ValueError("meeting_declined needs slot_id")
        before = len(constraints.blocked)
        constraints.blocked = [s for s in constraints.blocked if s.id != slot_id]
        effects.append(f"meeting {slot_id} declined" + ("" if before != len(
            constraints.blocked) else " (was not blocking the agenda)"))
        graph.append(("merge_node", ("Meeting", slot_id), {"status": "declined", **stamp}))
    elif change.type == "user_skipped":
        assert target is not None
        if target.id not in constraints.excluded_event_ids:
            constraints.excluded_event_ids.append(target.id)
        constraints.fixed_event_ids = [i for i in constraints.fixed_event_ids if i != target.id]
        effects.append(f"user skips '{target.title}'")
    elif change.type == "new_contact_met":
        if not change.person_id:
            raise ValueError("new_contact_met needs person_id")
        if change.person_id not in met:
            met.append(change.person_id)
        effects.append(f"met {change.person_id}: no longer a target for ranking")
        meeting_id = f"met-{change.person_id}"
        graph.append(("merge_node", ("Meeting", meeting_id), {"status": "met", **stamp}))
        graph.append(("merge_edge", ("Meeting", meeting_id, "INVOLVES", "Person",
                                     change.person_id), {"source": change.source_mode}))

    new_state = state.model_copy(update={
        "events": events, "constraints": constraints,
        "presence_overrides": overrides, "met_person_ids": met,
    })
    writes, errors = _write_graph(store, graph)
    return ChangeResult(state=new_state, effects=effects, graph_writes=writes, errors=errors)


def _write_graph(store: GraphStore | None, ops: list[tuple[str, tuple[Any, ...], dict[str, Any]]]
                 ) -> tuple[list[str], list[str]]:
    if store is None:
        return [], []
    done: list[str] = []
    errors: list[str] = []
    for method, args, props in ops:
        clean = {k: v for k, v in props.items() if v is not None}
        try:
            getattr(store, method)(*args, clean)
            done.append(f"{method}{args}")
        except Exception as exc:  # noqa: BLE001 - graph down must not break replanning
            errors.append(f"graph {method}{args} failed: {type(exc).__name__}")
    return done, errors


def replan(original: Plan | list[str], state: PlanningState) -> Plan:
    return optimize(state.candidates(), state.constraints, original=original)


class DiffEntry(_Model):
    event_id: str
    title: str
    why: str
    start_at: AwareDatetime | None = None
    previous_start_at: AwareDatetime | None = None


class PlanDiff(_Model):
    added: list[DiffEntry] = Field(default_factory=list)
    removed: list[DiffEntry] = Field(default_factory=list)
    moved: list[DiffEntry] = Field(default_factory=list)
    kept: list[str] = Field(default_factory=list)
    changes: int = 0
    reasons: list[str] = Field(default_factory=list)


def _short_why(item: PlanItem) -> str:
    return "; ".join(item.reasons[:2]) or f"utility {item.utility:.1f}"


def diff(old: Plan, new: Plan) -> PlanDiff:
    old_ids, new_ids = set(old.event_ids), set(new.event_ids)
    removed = []
    for event_id in sorted(old_ids - new_ids):
        item = old.item(event_id)
        assert item
        rej = new.rejection(event_id)
        removed.append(DiffEntry(event_id=event_id, title=item.title,
                                 why=rej.reason if rej else "no longer a candidate",
                                 previous_start_at=item.start_at))
    added = [DiffEntry(event_id=i.event_id, title=i.title, why=_short_why(i), start_at=i.start_at)
             for i in new.items if i.event_id not in old_ids]
    moved: list[DiffEntry] = []
    kept: list[str] = []
    for item in new.items:
        before = old.item(item.event_id)
        if before is None:
            continue
        if (before.start_at, before.end_at) != (item.start_at, item.end_at):
            moved.append(DiffEntry(
                event_id=item.event_id, title=item.title, start_at=item.start_at,
                previous_start_at=before.start_at,
                why=f"time changed from {before.start_at:%a %H:%M} to {item.start_at:%a %H:%M}"))
        else:
            kept.append(item.event_id)

    reasons: list[str] = []
    old_items = {i.event_id: i for i in old.items}
    new_items = {i.event_id: i for i in new.items}
    pending_added = list(added)
    for rem in removed:
        old_item = old_items[rem.event_id]
        same_day = [a for a in pending_added if new_items[a.event_id].day == old_item.day]
        if same_day:
            rep = min(same_day, key=lambda a: (
                abs((new_items[a.event_id].start_at - old_item.start_at).total_seconds()),
                a.event_id))
            pending_added.remove(rep)
            new_item = new_items[rep.event_id]
            delta = (new_item.travel_minutes_from_previous or 0) - (
                old_item.travel_minutes_from_previous or 0)
            travel = (f"Travel adds {delta} min." if delta > 0 else
                      f"Travel saves {-delta} min." if delta < 0 else "Travel unchanged.")
            reasons.append(f"I replace '{rem.title}' with '{rep.title}'. '{rem.title}': "
                           f"{rem.why}. '{rep.title}': {rep.why}. {travel}")
        else:
            reasons.append(f"I drop '{rem.title}': {rem.why}.")
    for add in pending_added:
        reasons.append(f"I add '{add.title}': {add.why}.")
    for mov in moved:
        reasons.append(f"'{mov.title}' stays in the plan: {mov.why}.")
    fixed_hit = any(old_items[r.event_id].fixed for r in removed)
    if not fixed_hit and (removed or added or moved):
        reasons.append("No fixed appointment touched.")
    if not (removed or added or moved):
        reasons.append("No change needed: the agenda still holds.")
    return PlanDiff(added=added, removed=removed, moved=moved, kept=sorted(kept),
                    changes=len(added) + len(removed), reasons=reasons)
