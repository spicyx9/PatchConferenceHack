"""Deterministic event to conference linking (rattachement).

Scores how likely an Event is related to a Conference from six independent
signals (see docs/knowledge/05-events.md, section "Rattachement"). Pure and
offline: no network, no LLM. A heuristic score is never evidence of official
affiliation, so ``apply_link`` only ever produces ``candidate`` or ``unknown``.
"""

from __future__ import annotations

import math
import re
import string
from collections.abc import Iterable, Sequence
from datetime import timedelta
from typing import Any
from zoneinfo import ZoneInfo

from conferge.core.schemas import Conference, Event

WEIGHTS: dict[str, float] = {
    "mentions_conference": 0.3,
    "date_within_window": 0.2,
    "geo_within_radius": 0.15,
    "host_is_sponsor_or_speaker": 0.2,
    "topic_overlap": 0.1,
    "listed_on_aggregator": 0.05,
}
INCLUSION_THRESHOLD = 0.5
TOPIC_SIMILARITY_THRESHOLD = 0.35
MIN_NAME_CHARS = 3
EARTH_RADIUS_KM = 6371.0088
CONFIRMED_RELATIONS = frozenset({"official", "confirmed_side_event"})

Signals = dict[str, dict[str, Any]]

_PUNCT_TABLE = str.maketrans({c: " " for c in string.punctuation})


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance in kilometres."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(min(1.0, math.sqrt(a)))


def normalize_name(value: str) -> str:
    """Casefold, replace punctuation by spaces and collapse whitespace."""
    return " ".join(value.casefold().translate(_PUNCT_TABLE).split())


def _contains_tokens(haystack: list[str], needle: list[str]) -> bool:
    n = len(needle)
    if n == 0 or n > len(haystack):
        return False
    return any(haystack[i : i + n] == needle for i in range(len(haystack) - n + 1))


def _phrase_regex(phrase: str) -> re.Pattern[str]:
    # Whole-word match; tolerate any whitespace run between words.
    parts = [re.escape(p) for p in phrase.split()]
    return re.compile(r"(?<!\w)" + r"\s+".join(parts) + r"(?!\w)", re.IGNORECASE)


def _event_text(event: Event) -> str:
    return " ".join(x for x in (event.title, event.description) if x)


def _signal(value: bool, detail: str) -> dict[str, Any]:
    return {"value": value, "detail": detail}


def _mentions(event: Event, conference: Conference, aliases: Iterable[str]) -> dict[str, Any]:
    text = _event_text(event)
    names = [conference.name, *aliases]
    seen: set[str] = set()
    for name in names:
        name = name.strip()
        if not name or name.casefold() in seen:
            continue
        seen.add(name.casefold())
        if _phrase_regex(name).search(text):
            return _signal(True, f"mentions '{name}' in title or description")
    return _signal(False, "no mention of conference name or aliases")


def _date_window(event: Event, conference: Conference, window_days: int) -> dict[str, Any]:
    if event.start_at is None:
        return _signal(False, "start unknown")
    local_day = event.start_at.astimezone(ZoneInfo(conference.timezone)).date()
    lo = conference.start_date - timedelta(days=window_days)
    hi = conference.end_date + timedelta(days=window_days)
    inside = lo <= local_day <= hi
    rel = "within" if inside else "outside"
    return _signal(
        inside,
        f"starts {local_day.isoformat()} ({conference.timezone}), {rel} "
        f"{lo.isoformat()}..{hi.isoformat()}",
    )


def _geo(event: Event, conference: Conference, radius_km: float) -> dict[str, Any]:
    venue = event.venue
    if conference.latitude is None or conference.longitude is None:
        return _signal(False, "conference coordinates unknown")
    if venue is None or venue.latitude is None or venue.longitude is None:
        if (
            venue is not None
            and venue.city
            and normalize_name(venue.city) == normalize_name(conference.city)
        ):
            return _signal(False, "same city, no coordinates")
        return _signal(False, "venue coordinates unknown")
    dist = haversine_km(venue.latitude, venue.longitude, conference.latitude, conference.longitude)
    inside = dist <= radius_km
    rel = "within" if inside else "beyond"
    return _signal(inside, f"{dist:.2f} km from conference venue, {rel} {radius_km:g} km")


def _host_match(
    event: Event, sponsor_names: Sequence[str], speaker_names: Sequence[str]
) -> dict[str, Any]:
    if not event.organizer_names:
        return _signal(False, "organizers unknown")
    candidates = [(n, "sponsor") for n in sponsor_names] + [(n, "speaker") for n in speaker_names]
    for org in event.organizer_names:
        org_norm = normalize_name(org)
        if len(org_norm) < MIN_NAME_CHARS:
            continue
        org_tokens = org_norm.split()
        for name, kind in candidates:
            name_norm = normalize_name(name)
            if len(name_norm) < MIN_NAME_CHARS:
                continue
            name_tokens = name_norm.split()
            if _contains_tokens(org_tokens, name_tokens) or _contains_tokens(
                name_tokens, org_tokens
            ):
                return _signal(True, f"organizer '{org}' matches {kind} '{name}'")
    return _signal(False, "no organizer matches a sponsor or speaker")


def _topics(
    event: Event, conference: Conference, topic_similarity: float | None
) -> dict[str, Any]:
    if topic_similarity is not None:
        hit = topic_similarity > TOPIC_SIMILARITY_THRESHOLD
        return _signal(
            hit,
            f"topic similarity {topic_similarity:.3f} vs threshold {TOPIC_SIMILARITY_THRESHOLD}",
        )
    if not conference.topics:
        return _signal(False, "lexical fallback: conference has no topics")
    text = " ".join([_event_text(event), *[f"| {t} |" for t in event.topics]])
    matched = [t for t in conference.topics if t.strip() and _phrase_regex(t).search(text)]
    share = len(matched) / len(conference.topics)
    if matched:
        return _signal(
            True,
            f"lexical fallback: matched {', '.join(matched)} "
            f"({len(matched)}/{len(conference.topics)}, share {share:.2f})",
        )
    return _signal(False, "lexical fallback: no conference topic found")


def compute_signals(
    event: Event,
    conference: Conference,
    *,
    aliases: list[str] | None = None,
    sponsor_names: Sequence[str] = (),
    speaker_names: Sequence[str] = (),
    listed_on_aggregator: bool = False,
    topic_similarity: float | None = None,
    window_days: int = 2,
    radius_km: float = 8.0,
) -> Signals:
    """Return signal name -> {"value": bool, "detail": str} for every weighted signal."""
    return {
        "mentions_conference": _mentions(event, conference, aliases or []),
        "date_within_window": _date_window(event, conference, window_days),
        "geo_within_radius": _geo(event, conference, radius_km),
        "host_is_sponsor_or_speaker": _host_match(event, sponsor_names, speaker_names),
        "topic_overlap": _topics(event, conference, topic_similarity),
        "listed_on_aggregator": _signal(
            bool(listed_on_aggregator),
            "listed on a conference aggregator" if listed_on_aggregator else "not on aggregator",
        ),
    }


def score_signals(signals: Signals) -> float:
    total = sum(WEIGHTS.values())
    hit = sum(w for name, w in WEIGHTS.items() if signals.get(name, {}).get("value") is True)
    return round(max(0.0, min(1.0, hit / total)), 4)


def link_to_conference(
    event: Event,
    conference: Conference,
    *,
    aliases: list[str] | None = None,
    sponsor_names: Sequence[str] = (),
    speaker_names: Sequence[str] = (),
    listed_on_aggregator: bool = False,
    topic_similarity: float | None = None,
    window_days: int = 2,
    radius_km: float = 8.0,
) -> tuple[float, Signals]:
    """Score an event against a conference. Returns (score in [0, 1], signals)."""
    signals = compute_signals(
        event,
        conference,
        aliases=aliases,
        sponsor_names=sponsor_names,
        speaker_names=speaker_names,
        listed_on_aggregator=listed_on_aggregator,
        topic_similarity=topic_similarity,
        window_days=window_days,
        radius_km=radius_km,
    )
    return score_signals(signals), signals


def evidence_strings(signals: Signals) -> list[str]:
    """Human-readable evidence for the true signals, in WEIGHTS order."""
    return [
        f"{name}: {signals[name]['detail']}"
        for name in WEIGHTS
        if signals.get(name, {}).get("value") is True
    ]


def apply_link(event: Event, conference: Conference, **kwargs: Any) -> Event:
    """Return a copy of ``event`` annotated with the link score.

    Never sets ``official`` or ``confirmed_side_event``. If the source adapter
    already established one of those, the relation and its evidence are kept
    and only ``relation_score`` is added.
    """
    score, signals = link_to_conference(event, conference, **kwargs)
    if event.conference_relation in CONFIRMED_RELATIONS:
        update: dict[str, Any] = {"relation_score": score}
        if event.conference_id is None:
            update["conference_id"] = conference.id
        return event.model_copy(update=update, deep=True)
    relation = "candidate" if score >= INCLUSION_THRESHOLD else "unknown"
    return event.model_copy(
        update={
            "conference_id": conference.id,
            "relation_score": score,
            "relation_evidence": evidence_strings(signals),
            "conference_relation": relation,
        },
        deep=True,
    )
