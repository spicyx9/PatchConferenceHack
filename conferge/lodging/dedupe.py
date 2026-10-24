"""Conservative cross-platform hotel deduplication.

Same group only when both stays have coordinates less than 75 m apart AND their
normalized names agree (equal, containment, or token Jaccard >= 0.6). Airbnb listings
(approximate coordinates, room-level names) are never merged with other providers.
Every source row is kept; only ``dedup_group`` is set, with the reasons returned.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from conferge.core.schemas import Lodging
from conferge.lodging._common import AIRBNB
from conferge.lodging.distance import haversine_m

MAX_DISTANCE_M = 75.0
_STOPWORDS = frozenset({
    "the", "a", "an", "and", "at", "by", "of", "on", "in", "hotel", "hotels", "sf", "san",
    "francisco", "marriott", "hilton", "hyatt", "ihg", "kimpton", "autograph", "collection",
    "curio", "tapestry", "tribute", "portfolio", "joie", "de", "vivre", "suites", "resort",
})


def normalize_name(name: str) -> str:
    text = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    text = re.sub(r"[^a-z0-9 ]+", " ", text.replace("&", " and "))
    return " ".join(t for t in text.split() if t not in _STOPWORDS)


def _names_agree(a: str, b: str) -> tuple[bool, str]:
    if not a or not b:
        return False, "empty normalized name"
    if a == b:
        return True, "same normalized name"
    if f" {a} " in f" {b} " or f" {b} " in f" {a} ":
        return True, "normalized name containment"
    ta, tb = set(a.split()), set(b.split())
    jaccard = len(ta & tb) / len(ta | tb)
    return jaccard >= 0.6, f"token jaccard {jaccard:.2f}"


@dataclass
class DedupGroup:
    group_id: str
    member_ids: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)


def _coords(lodging: Lodging) -> tuple[float, float] | None:
    v = lodging.venue
    if v is None or v.latitude is None or v.longitude is None:
        return None
    return v.latitude, v.longitude


def same_property(a: Lodging, b: Lodging) -> tuple[bool, str]:
    if a.id == b.id:
        return True, "same provider id"
    if AIRBNB in (a.provider, b.provider) and a.provider != b.provider:
        return False, "airbnb never merged across providers"
    if a.provider == b.provider:
        return False, "same provider, different id"
    ca, cb = _coords(a), _coords(b)
    if ca is None or cb is None:
        return False, "missing coordinates"
    meters = haversine_m(ca[0], ca[1], cb[0], cb[1])
    if meters >= MAX_DISTANCE_M:
        return False, f"{meters:.0f} m apart"
    agree, why = _names_agree(normalize_name(a.name), normalize_name(b.name))
    return agree, f"{meters:.0f} m apart, {why}"


def dedupe(lodgings: list[Lodging]) -> tuple[list[Lodging], list[DedupGroup]]:
    """Assign ``dedup_group``; keeps every row. Groups of one are not reported."""
    groups: list[DedupGroup] = []
    members: list[list[Lodging]] = []
    for lodging in lodgings:
        placed = False
        for group, rows in zip(groups, members, strict=True):
            matches = [same_property(lodging, row) for row in rows]
            if all(ok for ok, _ in matches):
                group.member_ids.append(lodging.id)
                group.reasons.append(f"{lodging.id}: {matches[0][1]}")
                rows.append(lodging)
                placed = True
                break
        if not placed:
            groups.append(DedupGroup(group_id=f"stay:{lodging.id}", member_ids=[lodging.id]))
            members.append([lodging])
    out: list[Lodging] = []
    by_id = {}
    for group in groups:
        for member in group.member_ids:
            by_id[member] = group.group_id
    for lodging in lodgings:
        out.append(lodging.model_copy(update={"dedup_group": by_id[lodging.id]}))
    return out, [g for g in groups if len(g.member_ids) > 1]
