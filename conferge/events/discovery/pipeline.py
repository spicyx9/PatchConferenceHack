"""End-to-end discovery: queries -> candidate URLs -> routing -> detail pages ->
conference linking -> conservative dedup.

An Event is produced only from a fetched detail page (platform adapter or
schema.org JSON-LD), never from a SERP title or snippet. Linking can at most mark
an Event as `candidate`; official relations come only from source adapters.
"""

from __future__ import annotations

import asyncio
import importlib
import re
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from conferge.core.schemas import (
    Conference,
    DataEnvelope,
    DataMode,
    DiscoveryResult,
    Event,
    RunReport,
    RunStatus,
    SourceRecord,
    SourceRef,
    Termination,
)
from conferge.events.discovery.dedupe import dedupe, normalize_title
from conferge.events.discovery.jsonld import normalize_jsonld
from conferge.events.discovery.link import apply_link
from conferge.events.discovery.queries import QueryPlan
from conferge.events.discovery.serp import DiscoveryError, SerpDiscoverySource

AGGREGATOR_PLATFORMS = frozenset({"aggregator"})


class CandidateOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_id: str
    url: str
    platform: str
    adapter: str
    confidence: float
    status: str  # verified | unverified | failed | skipped
    detail_provider: str | None = None
    event_ids: list[str] = Field(default_factory=list)
    error: str | None = None


class DiscoveryRun(BaseModel):
    """Full trace of one discovery run, ready for the API or the probe."""

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    discovery: DiscoveryResult
    outcomes: list[CandidateOutcome]
    events: DataEnvelope[Event]
    groups: list[dict[str, Any]] = Field(default_factory=list)


def plan_for_conference(
    conference: Conference, *, aliases: list[str] | None = None,
    sponsors: list[str] | None = None, hosts: list[str] | None = None,
    topics: list[str] | None = None,
) -> QueryPlan:
    return QueryPlan(
        city=conference.city, conference_name=conference.name, aliases=aliases or [],
        venue=conference.venue_name, start_date=conference.start_date,
        end_date=conference.end_date, sponsors=sponsors or [], hosts=hosts or [],
        topics=topics if topics is not None else list(conference.topics),
    )


def _sibling_normalizer(module: str, name: str) -> Callable[..., Event] | None:
    try:
        return getattr(importlib.import_module(module), name)
    except (ImportError, AttributeError):
        return None


def normalize_detail(record: SourceRecord, *, conference_id: str | None = None) -> list[Event]:
    """Detail SourceRecord -> Events using the owning adapter's normalizer."""
    payload = record.payload
    if record.provider == "luma":
        fn = _sibling_normalizer("conferge.events.luma", "normalize")
        return [fn(record, conference_id=conference_id)] if fn else []
    if record.provider == "partiful":
        fn = _sibling_normalizer("conferge.events.partiful", "normalize")
        return [fn(record, conference_id=conference_id)] if fn else []
    if record.provider == "facebook_events":
        from conferge.events.discovery.facebook import normalize as fb_normalize

        return [fb_normalize(record, conference_id=conference_id)]
    blocks: list[dict[str, Any]] = []
    if isinstance(payload.get("jsonld"), dict):  # eventbrite detail page
        blocks = [payload["jsonld"]]
    elif isinstance(payload.get("jsonld_events"), list):
        blocks = [b for b in payload["jsonld_events"] if isinstance(b, dict)]
    events = []
    for index, block in enumerate(blocks):
        event = normalize_jsonld(block, record, conference_id=conference_id)
        if index:
            event = event.model_copy(update={"id": f"{event.id}:{index}"})
        events.append(event)
    return events


def is_anchor_conference(event: Event, conference: Conference) -> bool:
    """True when a page's event object is the anchor conference itself (e.g. a
    sponsor page embedding the conference as JSON-LD), not a side event."""
    def strip_years(text: str) -> str:
        return " ".join(re.sub(r"\b20\d\d\b", " ", normalize_title(text)).split())

    return strip_years(event.title) == strip_years(conference.name)


def _envelope_mode(modes: set[str]) -> DataMode:
    if not modes:
        return "live"
    if len(modes) == 1:
        return next(iter(modes))  # type: ignore[return-value]
    return "mixed"


async def run(
    conference: Conference,
    *,
    source: SerpDiscoverySource,
    plan: QueryPlan | None = None,
    discovery: DiscoveryResult | None = None,
    sponsor_names: list[str] | None = None,
    speaker_names: list[str] | None = None,
    aliases: list[str] | None = None,
    max_details: int = 25,
    min_confidence: float = 0.25,
    detail_concurrency: int = 4,
) -> DiscoveryRun:
    """Run discovery for one conference. `discovery` lets callers pass an explicit
    fixture DiscoveryResult; otherwise `source.discover_plan` is called."""
    started = datetime.now(timezone.utc)
    plan = plan or plan_for_conference(conference, aliases=aliases, sponsors=sponsor_names)
    if discovery is None:
        discovery = await source.discover_plan(plan)
    outcomes: list[CandidateOutcome] = []
    to_fetch: list[SourceRecord] = []
    for cand in discovery.items:
        route = cand.payload.get("route") or {}
        outcome = CandidateOutcome(
            candidate_id=cand.source_id, url=cand.payload.get("canonical_url", ""),
            platform=route.get("platform", "generic"), adapter=route.get("adapter", "none"),
            confidence=float(cand.payload.get("confidence") or 0.0), status="skipped",
        )
        outcomes.append(outcome)
        if outcome.adapter in {"none", "official", "aggregators"}:
            outcome.error = "no detail adapter in window 04; left to its owning window"
        elif outcome.confidence < min_confidence:
            outcome.error = f"confidence {outcome.confidence} below {min_confidence}"
        elif len(to_fetch) >= max_details:
            outcome.error = f"detail budget max_details={max_details} reached"
        else:
            to_fetch.append(cand)
    by_id = {o.candidate_id: o for o in outcomes}
    sem = asyncio.Semaphore(max(1, detail_concurrency))

    async def fetch(cand: SourceRecord) -> tuple[SourceRecord, SourceRecord | None, str | None]:
        async with sem:
            try:
                ref = SourceRef(provider=cand.provider, source_id=cand.source_id,
                                url=cand.payload["canonical_url"])
                return cand, await source.fetch_details(ref), None
            except DiscoveryError as exc:
                return cand, None, str(exc)
            except Exception as exc:  # noqa: BLE001 - one bad page must not abort the run
                return cand, None, f"{exc.__class__.__name__}: {exc}"

    fetched = await asyncio.gather(*(fetch(c) for c in to_fetch))
    events: list[Event] = []
    errors: list[str] = list(discovery.errors)
    sponsors = sponsor_names or []
    speakers = speaker_names or []
    for cand, detail, err in fetched:
        outcome = by_id[cand.source_id]
        if detail is None:
            outcome.status = "unverified" if err and "unverified" in err else "failed"
            outcome.error = err
            continue
        outcome.detail_provider = detail.provider
        try:
            normalized = normalize_detail(detail, conference_id=conference.id)
        except Exception as exc:  # noqa: BLE001 - adapter drift is reported, not fatal
            outcome.status, outcome.error = "failed", f"normalize: {exc}"
            continue
        if not normalized:
            outcome.status, outcome.error = "unverified", "detail page had no event data"
            continue
        anchor = [e for e in normalized if is_anchor_conference(e, conference)]
        normalized = [e for e in normalized if e not in anchor]
        if anchor and not normalized:
            outcome.status = "unverified"
            outcome.error = "detail page describes the anchor conference itself, not a side event"
            continue
        on_aggregator = outcome.platform in AGGREGATOR_PLATFORMS
        for event in normalized:
            linked = apply_link(
                event, conference, aliases=aliases, sponsor_names=sponsors,
                speaker_names=speakers, listed_on_aggregator=on_aggregator,
            )
            linked = linked.model_copy(update={"relation_evidence": [
                *linked.relation_evidence,
                f"discovered via SERP query: {cand.payload['discovered_by'][0]['query']}",
            ]}) if cand.payload.get("discovered_by") else linked
            events.append(linked)
            outcome.event_ids.append(linked.id)
        outcome.status = "verified"
    failures = [o for o in outcomes if o.status == "failed"]
    groups = dedupe(events)
    canonical = [g.canonical for g in groups]
    modes = {discovery.run_report.source_mode, *(e.evidence[0].source_mode for e in canonical
                                                 if e.evidence)}
    status: RunStatus = discovery.run_report.status
    if status == "ok" and failures:
        status = "degraded"
    detail_termination: Termination = "error" if failures else "not_applicable"
    detail_report = RunReport(
        provider="discovery_details", started_at=started, finished_at=datetime.now(timezone.utc),
        status="degraded" if failures else "ok", termination=detail_termination,
        source_mode="live", fetched_count=len(to_fetch),
        unique_count=sum(1 for o in outcomes if o.status == "verified"), pages=len(to_fetch),
        errors=[f"{o.url}: {o.error}" for o in failures],
        warnings=[f"{o.url}: {o.error}" for o in outcomes if o.status == "unverified"],
    )
    envelope = DataEnvelope[Event](
        items=canonical, source_mode=_envelope_mode(modes), status=status,
        reports=[discovery.run_report, detail_report], errors=errors,
    )
    return DiscoveryRun(
        discovery=discovery, outcomes=outcomes, events=envelope,
        groups=[{
            "canonical_id": g.canonical.id, "decision": g.decision,
            "merge_confidence": g.merge_confidence, "reasons": g.reasons,
            "member_ids": [m.id for m in g.members],
        } for g in groups],
    )
