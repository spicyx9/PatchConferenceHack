"""Deterministic agenda optimizer with minimal-change replanning.

Design (inspired by re:Invent Pathfinder's optimizer/explain split and PyconUK
ConferenceScheduler's ``original_schedule`` idea; no code copied):

* Hard filters first: unknown times, cancelled/sold out/postponed, user
  exclusions, blocked slots (meetings, flights), daily time window, optional
  registration-evidence requirement.
* Per local day, an exact longest-path dynamic program over events sorted by
  start time. ``b`` may follow ``a`` only if ``a.end + travel(a, b) <= b.start``,
  so the selected agenda never overlaps, travel included. The path length is
  capped by ``max_per_day``. Fixed events get a dominating weight and events that
  clash with a fixed one are removed beforehand.
* Minimal change: with ``original`` given, every kept item earns
  ``change_penalty`` and every newly added item pays it, so a replan only swaps
  items when the utility gain beats the cost of changing the user's day.
* Budget (events only, known USD prices): drop the selected paid item with the
  lowest utility per dollar and re-solve until the known total fits. Unknown
  prices are reported, never assumed zero.

Ties are broken by the stable (start, end, id) order, so output is reproducible.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from conferge.agents.antifomo.models import (
    Candidate, Constraints, Plan, PlanItem, Rejection, RejectCode,
)
from conferge.agents.antifomo.travel import compatible, fits_before, local_day, travel_minutes
from conferge.core.schemas import Event

_FIXED_WEIGHT = 1_000_000.0
_EPS = 1e-9
_UNAVAILABLE = {"cancelled", "sold_out", "postponed"}


def _as_candidates(items: Sequence[Candidate | Event]) -> list[Candidate]:
    out: list[Candidate] = []
    for item in items:
        if isinstance(item, Candidate):
            out.append(item)
        else:
            from conferge.agents.antifomo.scoring import score_event

            out.append(score_event(item, [], []))
    return sorted(out, key=lambda c: c.id)


def _original_ids(original: Plan | Sequence[str] | None) -> set[str] | None:
    if original is None:
        return None
    if isinstance(original, Plan):
        return set(original.event_ids)
    return set(original)


def _overlaps(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime) -> bool:
    return a_start < b_end and b_start < a_end


def _prefilter(cand: Candidate, c: Constraints, over_budget: set[str]) -> tuple[RejectCode, str] | None:
    ev = cand.event
    if ev.start_at is None or ev.end_at is None:
        return "time_unknown", "start or end time unknown; conflicts cannot be verified"
    if ev.status in _UNAVAILABLE:
        return "unavailable", f"event is {ev.status.replace('_', ' ')}"
    if ev.id in c.excluded_event_ids:
        return "excluded_by_user", "skipped or excluded by the user"
    if ev.id in over_budget:
        return "over_budget", "dropped to keep known event spend within budget"
    if c.require_registration_evidence and ev.registration_url is None:
        return "missing_registration_evidence", "no registration link found"
    for slot in c.blocked:
        if _overlaps(ev.start_at, ev.end_at, slot.start, slot.end):
            return "blocked_slot", f"overlaps fixed appointment '{slot.label}'"
    tz = ZoneInfo(ev.timezone or c.timezone)
    start, end = ev.start_at.astimezone(tz), ev.end_at.astimezone(tz)
    if c.day_start and start.time() < c.day_start:
        return "outside_daily_window", f"starts before {c.day_start.isoformat('minutes')}"
    if c.day_end and (end.date() > start.date() or end.time() > c.day_end):
        return "outside_daily_window", f"ends after {c.day_end.isoformat('minutes')}"
    return None


def _solve_day(
    cands: list[Candidate], weights: dict[str, float], c: Constraints,
) -> list[Candidate]:
    """Exact best chain of mutually compatible events, at most max_per_day long."""
    n, k_max = len(cands), c.max_per_day
    if n == 0:
        return []
    events = [x.event for x in cands]
    fits = [[i < j and fits_before(events[i], events[j], c) for j in range(n)] for i in range(n)]
    neg = float("-inf")
    best = [[neg] * (k_max + 1) for _ in range(n)]
    prev = [[-1] * (k_max + 1) for _ in range(n)]
    for j in range(n):
        w = weights[cands[j].id]
        best[j][1] = w
        for k in range(2, k_max + 1):
            for i in range(j):
                if fits[i][j] and best[i][k - 1] > neg:
                    score = best[i][k - 1] + w
                    if score > best[j][k] + _EPS:
                        best[j][k], prev[j][k] = score, i
    top, end = 0.0, None
    for j in range(n):
        for k in range(1, k_max + 1):
            if best[j][k] > top + _EPS:
                top, end = best[j][k], (j, k)
    chain: list[Candidate] = []
    while end is not None:
        j, k = end
        chain.append(cands[j])
        end = (prev[j][k], k - 1) if prev[j][k] >= 0 else None
    return list(reversed(chain))


def _select(
    cands: list[Candidate], c: Constraints, orig: set[str] | None, over_budget: set[str],
) -> tuple[list[Candidate], list[Rejection], list[str], dict[str, float]]:
    rejected: list[Rejection] = []
    warnings: list[str] = []
    by_day: dict[str, list[Candidate]] = defaultdict(list)
    for cand in cands:
        hit = _prefilter(cand, c, over_budget)
        if hit:
            if cand.id in c.fixed_event_ids:
                warnings.append(f"fixed event {cand.id} cannot be kept: {hit[1]}")
            rejected.append(Rejection(event_id=cand.id, title=cand.event.title, code=hit[0],
                                      reason=hit[1], utility=cand.utility))
            continue
        assert cand.event.start_at is not None
        by_day[local_day(cand.event.start_at, cand.event.timezone or c.timezone)].append(cand)

    weights: dict[str, float] = {}
    for cand in cands:
        w = cand.utility
        if orig is not None:
            w += c.change_penalty if cand.id in orig else -c.change_penalty
        if cand.id in c.fixed_event_ids:
            w += _FIXED_WEIGHT
        weights[cand.id] = w

    selected: list[Candidate] = []
    for day in sorted(by_day):
        day_cands = sorted(by_day[day], key=lambda x: (x.event.start_at, x.event.end_at, x.id))
        fixed = sorted((x for x in day_cands if x.id in c.fixed_event_ids),
                       key=lambda x: (-x.utility, x.id))
        kept_fixed: list[Candidate] = []
        kept_ids: set[str] = set()
        for f in fixed:
            clash = next((k for k in kept_fixed if not compatible(f.event, k.event, c)), None)
            if clash:
                warnings.append(f"fixed events {f.id} and {clash.id} overlap; kept {clash.id}")
                weights[f.id] -= _FIXED_WEIGHT
            else:
                kept_fixed.append(f)
                kept_ids.add(f.id)
        pool: list[Candidate] = []
        for cand in day_cands:
            if cand.id in kept_ids:
                pool.append(cand)
                continue
            clash = next((k for k in kept_fixed if not compatible(cand.event, k.event, c)), None)
            if clash:
                rejected.append(Rejection(
                    event_id=cand.id, title=cand.event.title, code="conflicts_with_fixed",
                    reason=f"clashes with fixed '{clash.event.title}'", blocking_event_id=clash.id,
                    utility=cand.utility))
            else:
                pool.append(cand)
        if len(kept_fixed) > c.max_per_day:
            warnings.append(f"{day}: more fixed events than max_per_day={c.max_per_day}")
        chosen = _solve_day(pool, weights, c)
        selected += chosen
        chosen_ids = {x.id for x in chosen}
        for cand in pool:
            if cand.id in chosen_ids:
                continue
            rejected.append(_why_not(cand, chosen, weights[cand.id], c))
    return selected, rejected, warnings, weights


def _why_not(cand: Candidate, chosen: list[Candidate], weight: float, c: Constraints) -> Rejection:
    base = {"event_id": cand.id, "title": cand.event.title, "utility": cand.utility}
    clashes = [x for x in chosen if not compatible(cand.event, x.event, c)]
    if clashes:
        block = max(clashes, key=lambda x: (x.utility, x.id))
        minutes, basis = travel_minutes(cand.event, block.event, c)
        travel = "" if basis == "same_venue" else f" incl. {minutes} min travel"
        return Rejection(**base, code="conflict", blocking_event_id=block.id, reason=(
            f"overlaps '{block.event.title}'{travel}; utility {cand.utility:.1f} vs "
            f"{block.utility:.1f}"))
    if len(chosen) >= c.max_per_day:
        return Rejection(**base, code="day_full", reason=f"day already has {c.max_per_day} items")
    if cand.utility <= 0:
        reason = "no goal alignment (utility 0)"
    elif weight <= 0:
        reason = "utility does not outweigh the cost of changing the plan"
    else:
        reason = "a higher-value combination fills the day"
    return Rejection(**base, code="low_utility", reason=reason)


def optimize(
    candidates: Sequence[Candidate | Event],
    constraints: Constraints | None = None,
    original: Plan | Sequence[str] | None = None,
) -> Plan:
    c = constraints or Constraints()
    cands = _as_candidates(candidates)
    orig = _original_ids(original)
    over_budget: set[str] = set()
    while True:
        selected, rejected, warnings, _ = _select(cands, c, orig, over_budget)
        if c.budget_usd is None:
            break
        spent = sum((x.cost_usd for x in selected if x.cost_usd), Decimal("0"))
        if spent <= c.budget_usd:
            break
        paid = [x for x in selected if x.cost_usd and x.id not in c.fixed_event_ids]
        if not paid:
            warnings.append(f"fixed paid events exceed budget {c.budget_usd} USD")
            break
        drop = min(paid, key=lambda x: (x.utility / float(x.cost_usd or 1), x.id))
        over_budget.add(drop.id)
    return _build_plan(selected, rejected, warnings, c, orig)


def _build_plan(
    selected: list[Candidate], rejected: list[Rejection], warnings: list[str],
    c: Constraints, orig: set[str] | None,
) -> Plan:
    items: list[PlanItem] = []
    ordered = sorted(selected, key=lambda x: (x.event.start_at, x.id))
    prev_by_day: dict[str, Event] = {}
    unknown_cost: list[str] = []
    for cand in ordered:
        ev = cand.event
        assert ev.start_at and ev.end_at
        day = local_day(ev.start_at, ev.timezone or c.timezone)
        prev = prev_by_day.get(day)
        minutes, basis = (travel_minutes(prev, ev, c) if prev else (None, "first_of_day"))
        prev_by_day[day] = ev
        item_warnings: list[str] = []
        if ev.registration_url is None:
            item_warnings.append("no registration evidence: a seat is not guaranteed")
        if basis == "unknown_default":
            item_warnings.append(f"travel time assumed {minutes} min (venue location unknown)")
        if cand.cost_usd is None:
            unknown_cost.append(ev.id)
        reasons = list(cand.reasons)
        if ev.id in c.fixed_event_ids:
            reasons.insert(0, "fixed by user")
        if orig is not None and ev.id in orig:
            reasons.append("kept from original plan")
        evidence = ev.evidence[0] if ev.evidence else None
        items.append(PlanItem(
            event_id=ev.id, title=ev.title, day=day, start_at=ev.start_at, end_at=ev.end_at,
            venue_name=ev.venue.name if ev.venue else None, utility=cand.utility,
            travel_minutes_from_previous=minutes, travel_basis=basis,
            availability="registration_link_found" if ev.registration_url else
            "no_registration_evidence",
            fixed=ev.id in c.fixed_event_ids,
            kept_from_original=None if orig is None else ev.id in orig,
            targets_confirmed=cand.targets_confirmed, targets_probable=cand.targets_probable,
            reasons=reasons,
            source_mode=evidence.source_mode if evidence else None,
            collected_at=evidence.collected_at if evidence else None,
            warnings=item_warnings,
        ))
    selected_ids = {x.event_id for x in items}
    changes = None if orig is None else len(selected_ids ^ orig)
    return Plan(
        items=items,
        rejected=sorted(rejected, key=lambda r: r.event_id),
        total_utility=round(sum(i.utility for i in items), 2),
        known_cost_usd=sum((x.cost_usd for x in selected if x.cost_usd), Decimal("0")),
        unknown_cost_event_ids=sorted(unknown_cost),
        warnings=warnings,
        changes_vs_original=changes,
    )


def explain(plan: Plan) -> list[str]:
    """Plain-text rationale: why each item, and why each alternative was rejected."""
    lines: list[str] = []
    for item in plan.items:
        when = item.start_at.strftime("%a %d %b %H:%M")
        travel = ("" if item.travel_minutes_from_previous is None else
                  f", {item.travel_minutes_from_previous} min from previous ({item.travel_basis})")
        why = "; ".join(item.reasons) or "fits the day"
        lines.append(f"KEEP {when} {item.title} (U={item.utility:.1f}{travel}): {why}")
        lines += [f"  warning: {w}" for w in item.warnings]
    for rej in plan.rejected:
        lines.append(f"SKIP {rej.title} [{rej.code}]: {rej.reason}")
    lines += [f"WARNING: {w}" for w in plan.warnings]
    return lines
