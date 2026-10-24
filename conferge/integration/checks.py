"""Data-truth checks run on assembled records (CLAUDE.md rules 5 to 7)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from conferge.core.schemas import Event, Opportunity, Person
from conferge.integration.sources import SourceSlice

_CONFIRMED_PARTICIPATION = {"confirmed_speaker", "confirmed_organizer"}


@dataclass
class CheckResult:
    name: str
    passed: bool
    detail: str
    findings: list[str] = field(default_factory=list)


def _evidence_issues(kind: str, item: Any, slice_mode: str) -> list[str]:
    evidence = getattr(item, "evidence", [])
    if not evidence:
        return [f"{kind} {item.id}: no evidence (source_mode/collected_at unknown)"]
    issues = []
    for ev in evidence:
        if ev.collected_at is None:
            issues.append(f"{kind} {item.id}: evidence from {ev.provider} has no collected_at")
        if ev.source_mode != slice_mode and slice_mode != "mixed":
            issues.append(f"{kind} {item.id}: evidence says {ev.source_mode}, "
                          f"slice says {slice_mode}")
    return issues


def provenance(slices: list[SourceSlice]) -> CheckResult:
    findings: list[str] = []
    total = 0
    for s in slices:
        for kind, items in (("event", s.events), ("person", s.people),
                            ("company", s.companies)):
            for item in items:
                total += 1
                findings.extend(f"[{s.name}] {f}" for f in _evidence_issues(kind, item,
                                                                         s.source_mode))
    return CheckResult("provenance", not findings,
                       f"{total} records, {len(findings)} without full source_mode/collected_at",
                       findings)


def labels(slices: list[SourceSlice]) -> CheckResult:
    """A fixture path must never yield a live label and a live failure must not carry items."""
    findings = []
    for s in slices:
        if s.attempted == "fixture" and s.source_mode != "fixture":
            findings.append(f"{s.name}: fixture loader reported source_mode={s.source_mode}")
        if s.attempted == "live" and s.source_mode == "fixture":
            findings.append(f"{s.name}: live run returned fixture data")
        if s.status == "failed" and s.count and s.attempted == "live":
            findings.append(f"{s.name}: failed live run still returned {s.count} records")
        for r in s.reports:
            if r.status == "ok" and r.termination not in {"exhausted", "not_applicable"}:
                findings.append(f"{s.name}: report ok with termination {r.termination}")
    return CheckResult("labels", not findings, f"{len(slices)} slices checked", findings)


def relations(events: list[Event]) -> CheckResult:
    findings = []
    for e in events:
        if e.conference_relation in {"official", "confirmed_side_event"} and not e.relation_evidence:
            findings.append(f"{e.id}: {e.conference_relation} without evidence")
        if e.start_at is not None and e.start_at.tzinfo is None:
            findings.append(f"{e.id}: naive start_at")
    counts: dict[str, int] = {}
    for e in events:
        counts[e.conference_relation] = counts.get(e.conference_relation, 0) + 1
    return CheckResult("relations", not findings,
                       ", ".join(f"{k}={v}" for k, v in sorted(counts.items())), findings)


def opportunities(opps: list[Opportunity], people: list[Person], events: list[Event],
                  data_mode: str, result_mode: str) -> CheckResult:
    by_id = {p.id: p for p in people}
    event_ids = {e.id for e in events}
    findings = []
    if data_mode != "live" and result_mode == "live":
        findings.append(f"agent labelled result live over {data_mode} data")
    for o in opps:
        for pid in o.person_ids:
            if pid not in by_id:
                findings.append(f"{o.id}: unknown person {pid}")
            elif o.presence == "confirmed" and by_id[pid].participation not in _CONFIRMED_PARTICIPATION:
                findings.append(f"{o.id}: presence confirmed but {pid} is "
                                f"{by_id[pid].participation}")
        if o.event_id and o.event_id not in event_ids:
            findings.append(f"{o.id}: unknown event {o.event_id}")
    return CheckResult("opportunities", not findings, f"{len(opps)} opportunities", findings)
