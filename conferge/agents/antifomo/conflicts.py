"""Anti-FOMO: pairwise conflicts and an explained verdict for each.

Conflicts are computed locally from normalized events (same rule as
``conferge.graph.queries.conflicts``: ``start < other.end and end > other.start``)
extended with the travel buffer between venues. The verdict is decided by
opportunity (utility breakdown and target people), never by topic alone, and
never by an LLM. ``text`` is a deterministic template; an LLM may rephrase it
later from the same breakdown but must not change ``chosen``.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from conferge.agents.antifomo.models import Candidate, Constraints
from conferge.agents.antifomo.travel import compatible, travel_minutes
from conferge.core.schemas import Person


class Conflict(BaseModel):
    model_config = ConfigDict(extra="forbid")
    a: str
    b: str
    kind: Literal["time_overlap", "travel_overlap"]
    travel_minutes: int
    travel_basis: str


class Alternative(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event_id: str
    title: str
    why: str


class Verdict(BaseModel):
    model_config = ConfigDict(extra="forbid")
    a: str
    b: str
    chosen: str
    margin: float
    reasons: list[str] = Field(default_factory=list)
    missed: list[str] = Field(default_factory=list)
    alternative: Alternative | None = None
    breakdown: dict[str, dict[str, float]] = Field(default_factory=dict)
    text: str


def _schedulable(c: Candidate) -> bool:
    ev = c.event
    return ev.start_at is not None and ev.end_at is not None and ev.status not in {
        "cancelled", "sold_out", "postponed"}


def find_conflicts(candidates: Sequence[Candidate], constraints: Constraints | None = None
                   ) -> list[Conflict]:
    c = constraints or Constraints()
    cands = sorted((x for x in candidates if _schedulable(x)), key=lambda x: x.id)
    out: list[Conflict] = []
    for i, x in enumerate(cands):
        for y in cands[i + 1:]:
            if compatible(x.event, y.event, c):
                continue
            ex, ey = x.event, y.event
            assert ex.start_at and ex.end_at and ey.start_at and ey.end_at
            minutes, basis = travel_minutes(ex, ey, c)
            overlap = ex.start_at < ey.end_at and ey.start_at < ex.end_at
            out.append(Conflict(a=x.id, b=y.id, kind="time_overlap" if overlap else
                                "travel_overlap", travel_minutes=minutes, travel_basis=basis))
    return out


def _rank_key(c: Candidate) -> tuple[float, int, int, str]:
    assert c.event.start_at
    return (c.utility, len(c.targets_confirmed), len(c.targets_probable), c.id)


def _names(ids: list[str], people: dict[str, Person]) -> list[str]:
    return [people[i].name if i in people else i for i in ids]


def _alternative(
    loser: Candidate, winner: Candidate, others: Sequence[Candidate], c: Constraints,
    people: dict[str, Person],
) -> Alternative | None:
    """Another moment to catch what the loser offered, compatible with the winner."""
    targets = set(loser.targets_confirmed) | set(loser.targets_probable)
    options = sorted(
        (o for o in others if o.id not in {loser.id, winner.id} and _schedulable(o)
         and compatible(o.event, winner.event, c)),
        key=lambda o: (o.event.start_at, o.id))
    for o in options:
        shared = targets & (set(o.targets_confirmed) | set(o.targets_probable))
        if shared:
            names = ", ".join(sorted(_names(sorted(shared), people)))
            return Alternative(event_id=o.id, title=o.event.title,
                               why=f"{names} also at '{o.event.title}'")
    hosts = set(loser.event.organizer_ids) | set(loser.event.organizer_names)
    for o in options:
        if hosts & (set(o.event.organizer_ids) | set(o.event.organizer_names)):
            return Alternative(event_id=o.id, title=o.event.title,
                               why="same organizer hosts another slot")
    return None


def verdict(
    a: Candidate, b: Candidate, people: Sequence[Person] = (),
    others: Sequence[Candidate] = (), constraints: Constraints | None = None,
) -> Verdict:
    c = constraints or Constraints()
    by_id = {p.id: p for p in people}
    win, lose = (a, b) if _rank_key(a) >= _rank_key(b) else (b, a)
    margin = round(win.utility - lose.utility, 2)
    reasons = [f"'{win.event.title}' scores {win.utility:.1f} vs {lose.utility:.1f}"]
    wc, lc = len(win.targets_confirmed), len(lose.targets_confirmed)
    if wc != lc:
        reasons.append(f"{wc} confirmed target(s) vs {lc}")
    wp, lp = len(win.targets_probable), len(lose.targets_probable)
    if wp != lp:
        reasons.append(f"{wp} probable target(s) vs {lp}")
    if len(win.target_companies) > len(lose.target_companies):
        reasons.append(f"covers {len(win.target_companies)} target companies vs "
                       f"{len(lose.target_companies)}")
    if win.breakdown.get("R", 0) < lose.breakdown.get("R", 0):
        reasons.append("less uncertainty (relation, registration, venue)")
    if margin == 0:
        reasons.append("tie broken by confirmed targets, then probable, then id")

    missed: list[str] = []
    if lose.targets_confirmed:
        missed.append("confirmed: " + ", ".join(_names(lose.targets_confirmed, by_id)))
    if lose.targets_probable:
        missed.append("probable: " + ", ".join(_names(lose.targets_probable, by_id)))
    lost_topics = sorted({t.lower() for t in lose.event.topics} -
                         {t.lower() for t in win.event.topics})
    if lost_topics:
        missed.append("topics: " + ", ".join(lost_topics))
    alt = _alternative(lose, win, others, c, by_id)
    text = (f"Go to '{win.event.title}' rather than '{lose.event.title}'. "
            + "; ".join(reasons[1:] or reasons) + ".")
    if missed:
        text += " You miss " + "; ".join(missed) + "."
    if alt:
        text += f" Catch up: {alt.why}."
    return Verdict(
        a=a.id, b=b.id, chosen=win.id, margin=margin, reasons=reasons, missed=missed,
        alternative=alt, text=text,
        breakdown={a.id: {**a.breakdown, "U": a.utility}, b.id: {**b.breakdown, "U": b.utility}},
    )


def verdicts(
    candidates: Sequence[Candidate], people: Sequence[Person] = (),
    constraints: Constraints | None = None,
) -> list[Verdict]:
    by_id = {x.id: x for x in candidates}
    return [verdict(by_id[k.a], by_id[k.b], people, candidates, constraints)
            for k in find_conflicts(candidates, constraints)]
