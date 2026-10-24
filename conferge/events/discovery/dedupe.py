"""Conservative cross-source event deduplication.

Implements docs/knowledge/04-engineering-rules.md rule 6:

* same normalized source URL or same (provider, source_record_id) -> same (1.0)
* same normalized title + both starts known within 30 min + location or
  organizer corroboration (venue <= 500 m, shared organizer, same venue
  name or address) -> same (0.9)
* same normalized title without corroboration -> kept separate, flagged
  ``ambiguous`` with a pointer to the other event id. Never force merged.

All source rows are kept as group members. Input events are never mutated.
"""

from __future__ import annotations

import string
import unicodedata
from datetime import timedelta
from typing import Literal
from urllib.parse import urlsplit, urlunsplit

from pydantic import BaseModel, Field

from conferge.core.schemas import Event, Venue
from conferge.events.discovery.link import haversine_km

TIME_TOLERANCE = timedelta(minutes=30)
MAX_VENUE_DISTANCE_M = 500.0
URL_MATCH_CONFIDENCE = 1.0
FUZZY_MATCH_CONFIDENCE = 0.9

_PUNCT_TABLE = str.maketrans({c: " " for c in string.punctuation})


class DedupeGroup(BaseModel):
    canonical: Event
    members: list[Event]
    decision: Literal["unique", "same", "ambiguous"]
    merge_confidence: float = Field(ge=0, le=1)
    reasons: list[str] = Field(default_factory=list)


def _fold(s: str) -> str:
    decomposed = unicodedata.normalize("NFKD", s)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return " ".join(stripped.casefold().translate(_PUNCT_TABLE).split())


def normalize_title(s: str) -> str:
    """Casefold, strip accents, drop punctuation, collapse whitespace."""
    return _fold(s)


def normalize_url(url: object | None) -> str | None:
    """Lowercase scheme and host, drop query, fragment and trailing slash."""
    if url is None:
        return None
    raw = str(url).strip()
    if not raw:
        return None
    parts = urlsplit(raw)
    host = (parts.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    netloc = host if parts.port is None else f"{host}:{parts.port}"
    path = parts.path.rstrip("/")
    return urlunsplit(("", netloc, path, "", ""))


def _url_keys(event: Event) -> set[str]:
    keys = set()
    for u in [event.source_url, *[e.source_url for e in event.evidence]]:
        n = normalize_url(u)
        if n:
            keys.add(n)
    return keys


def _record_keys(event: Event) -> set[tuple[str, str]]:
    return {
        (e.provider.casefold(), e.source_record_id)
        for e in event.evidence
        if e.source_record_id
    }


def _venue_distance_m(a: Venue | None, b: Venue | None) -> float | None:
    if a is None or b is None:
        return None
    if None in (a.latitude, a.longitude, b.latitude, b.longitude):
        return None
    return haversine_km(a.latitude, a.longitude, b.latitude, b.longitude) * 1000.0


def _corroboration(a: Event, b: Event) -> str | None:
    dist = _venue_distance_m(a.venue, b.venue)
    if dist is not None and dist <= MAX_VENUE_DISTANCE_M:
        return f"venues {dist:.0f} m apart"
    orgs_a = {_fold(o) for o in a.organizer_names if _fold(o)}
    orgs_b = {_fold(o) for o in b.organizer_names if _fold(o)}
    shared = sorted(orgs_a & orgs_b)
    if shared:
        return f"shared organizer '{shared[0]}'"
    if a.venue is not None and b.venue is not None:
        for field in ("name", "address"):
            va, vb = getattr(a.venue, field), getattr(b.venue, field)
            if va and vb and _fold(va) and _fold(va) == _fold(vb):
                return f"same venue {field} '{va}'"
    return None


def _fuzzy_same(a: Event, b: Event) -> tuple[bool, str]:
    """Return (is_same, reason). Assumes normalized titles are equal."""
    if a.start_at is None or b.start_at is None:
        return False, "start time unknown"
    delta = abs(a.start_at - b.start_at)
    if delta > TIME_TOLERANCE:
        return False, f"starts {int(delta.total_seconds() // 60)} min apart"
    corr = _corroboration(a, b)
    if corr is None:
        dist = _venue_distance_m(a.venue, b.venue)
        if dist is not None:
            return False, f"venues {dist:.0f} m apart, no organizer or venue match"
        return False, "no location or organizer corroboration"
    minutes = int(delta.total_seconds() // 60)
    return True, f"same title, starts {minutes} min apart, {corr}"


def _filled_fields(event: Event) -> int:
    return sum(
        1
        for name in type(event).model_fields
        if getattr(event, name) not in (None, [], "", {})
    )


class _UnionFind:
    def __init__(self, n: int) -> None:
        self.parent = list(range(n))

    def find(self, i: int) -> int:
        while self.parent[i] != i:
            self.parent[i] = self.parent[self.parent[i]]
            i = self.parent[i]
        return i

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            # Keep the smaller index as root so order is stable.
            if rb < ra:
                ra, rb = rb, ra
            self.parent[rb] = ra


def dedupe(events: list[Event]) -> list[DedupeGroup]:
    """Group events conservatively. Groups are returned in first-seen order."""
    copies = [e.model_copy(deep=True) for e in events]
    n = len(copies)
    uf = _UnionFind(n)
    confidence: dict[int, float] = {}
    reasons: dict[int, list[str]] = {}
    ambiguous_with: dict[int, list[tuple[int, str]]] = {}

    def add_reason(i: int, j: int, conf: float, why: str) -> None:
        reasons.setdefault(i, []).append(why)
        reasons.setdefault(j, []).append(why)
        confidence[i] = min(confidence.get(i, 1.0), conf)
        confidence[j] = min(confidence.get(j, 1.0), conf)

    url_keys = [_url_keys(e) for e in copies]
    rec_keys = [_record_keys(e) for e in copies]
    titles = [normalize_title(e.title) for e in copies]

    for i in range(n):
        for j in range(i + 1, n):
            ids = f"{copies[i].id} ~ {copies[j].id}"
            shared_url = sorted(url_keys[i] & url_keys[j])
            if shared_url:
                uf.union(i, j)
                add_reason(i, j, URL_MATCH_CONFIDENCE, f"{ids}: same source url {shared_url[0]}")
                continue
            shared_rec = sorted(rec_keys[i] & rec_keys[j])
            if shared_rec:
                uf.union(i, j)
                prov, rid = shared_rec[0]
                add_reason(i, j, URL_MATCH_CONFIDENCE, f"{ids}: same {prov} record id {rid}")
                continue
            if titles[i] and titles[i] == titles[j]:
                same, why = _fuzzy_same(copies[i], copies[j])
                if same:
                    uf.union(i, j)
                    add_reason(i, j, FUZZY_MATCH_CONFIDENCE, f"{ids}: {why}")
                else:
                    ambiguous_with.setdefault(i, []).append((j, why))
                    ambiguous_with.setdefault(j, []).append((i, why))

    clusters: dict[int, list[int]] = {}
    for i in range(n):
        clusters.setdefault(uf.find(i), []).append(i)

    groups: list[DedupeGroup] = []
    for root in sorted(clusters):
        idx = clusters[root]
        idx_set = set(idx)
        members = [copies[i] for i in idx]
        best = max(range(len(members)), key=lambda k: (_filled_fields(members[k]), -k))
        group_reasons: list[str] = []
        for i in idx:
            for r in reasons.get(i, []):
                if r not in group_reasons:
                    group_reasons.append(r)
        amb: list[str] = []
        for i in idx:
            for j, why in ambiguous_with.get(i, []):
                if j in idx_set:
                    continue  # linked transitively through a stronger rule
                msg = (
                    f"same normalized title as {copies[j].id} but not merged: {why}"
                )
                if msg not in amb:
                    amb.append(msg)
        if len(idx) > 1:
            decision: Literal["unique", "same", "ambiguous"] = "same"
            conf = min(confidence.get(i, 1.0) for i in idx)
        elif amb:
            decision = "ambiguous"
            conf = 0.0
        else:
            decision = "unique"
            conf = 1.0
        groups.append(
            DedupeGroup(
                canonical=members[best],
                members=members,
                decision=decision,
                merge_confidence=conf,
                reasons=group_reasons + amb,
            )
        )
    return groups
