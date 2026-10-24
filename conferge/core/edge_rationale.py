"""Rule-based edge rationale and evidence ids, attached by ``GraphStore.merge_edge``.

Every edge carries ``rationale`` (one sentence, built from its own provenance
properties, never by an LLM) and ``evidence_ids`` (identifiers of evidence that
already exists: a source URL or a provider snapshot id). Only records the
application itself owns (the user's goals, plan, meetings, changes and the
planner's opportunities) may cite their own node id, as ``record:<Kind>:<id>``.
Any other edge without evidence is refused.
"""

from __future__ import annotations

from typing import Any

# Edge properties that hold an existing evidence identifier, strongest first.
EVIDENCE_KEYS = (
    "source_url", "evidence_url", "linkedin_source_url",
    "snapshot_id", "linkedin_snapshot_id", "raw_ref", "source_record_id",
)
# Node kinds the application writes itself: their id is the evidence of their edges.
RECORD_KINDS = frozenset({"User", "Goal", "Meeting", "Change", "Opportunity"})

_PAGES = {
    "rainfocus:github-universe-2026": "official GitHub Universe session page",
    "luma": "Luma event page",
    "partiful": "Partiful event page",
    "eventbrite": "Eventbrite event page",
    "conferenceparties": "conferenceparties.com side-event list",
    "booking": "Booking.com listing",
    "airbnb": "Airbnb listing",
    "brightdata:linkedin": "LinkedIn profile collected via Bright Data",
}


class MissingEvidence(ValueError):
    """An edge would be written without any evidence id."""


# Edges read off the session catalog; conference-level ones come from the official site.
_SESSION_VERIFICATIONS = frozenset({
    "event_record", "event_speaker_list", "event_organizer_list", "relation_evidence",
    "keyword_match", "person_record",
})


def _page(source: Any, verification: Any = None) -> str:
    name = str(source or "unknown source")
    if name.startswith("rainfocus:") and verification not in _SESSION_VERIFICATIONS:
        return _PAGES.get(name, "official session page").replace("session page", "website")
    if name in _PAGES:
        return _PAGES[name]
    if name.startswith("rainfocus:"):
        return f"official {name.removeprefix('rainfocus:')} session page"
    return f"{name} record"


def _day(value: Any) -> str | None:
    return str(value)[:10] if value else None


def _on(value: Any) -> str:
    day = _day(value)
    return f" on {day}" if day else ""


def evidence_ids(from_kind: str, from_id: str, props: dict[str, Any]) -> list[str]:
    """Existing evidence identifiers named by the edge properties, deduplicated."""
    ids: list[str] = []
    for key in EVIDENCE_KEYS:
        value = props.get(key)
        if value:
            ids.append(str(value))
    ids += [str(v) for v in props.get("evidence_ids") or [] if v]
    if not ids and from_kind in RECORD_KINDS:
        ids.append(f"record:{from_kind}:{from_id}")
    return list(dict.fromkeys(ids))


def rationale(relation: str, from_kind: str, props: dict[str, Any]) -> str:
    """One sentence saying why the edge exists, from its own provenance only."""
    verification = props.get("verification")
    source = props.get("source")
    page = _page(source, verification)
    if relation == "WORKS_AT" and props.get("linkedin_verification"):
        sentence = ("WORKS_AT corroborated by LinkedIn profile collected via Bright Data"
                    + _on(props.get("linkedin_observed_at")))
    elif relation == "WORKS_AT" and verification == "linkedin_profile":
        sentence = ("WORKS_AT stated by LinkedIn profile collected via Bright Data"
                    + _on(props.get("observed_at")))
    elif relation == "WORKS_AT" and verification == "person_record":
        sentence = f"Employer listed on the person profile of the {page}"
    elif relation == "SPEAKS_AT" and verification == "event_speaker_list":
        sentence = f"Listed as speaker on the {page}"
    elif relation == "SPEAKS_AT" and verification == "person_record":
        sentence = f"Speaker role stated on the person profile of the {page}"
    elif relation == "HOSTS" and verification == "event_organizer_list":
        sentence = f"Listed as organizer on the {page}"
    elif relation == "HOSTS" and verification == "person_record":
        sentence = f"Organizer role stated on the person profile of the {page}"
    elif relation == "ATTENDS_CONFIRMED" and verification == "public_attendee_listing":
        sentence = f"Publicly listed as attendee on the {page}"
    elif relation == "ABOUT" and verification == "user_goal":
        sentence = "Topic stated by the user in this goal"
    elif relation == "ABOUT" and verification == "keyword_match":
        sentence = f"Topic inferred by keyword match in the text of the {page}"
    elif relation == "ABOUT" and verification == "person_record":
        sentence = f"Topic listed on the person profile of the {page}"
    elif relation == "ABOUT":
        sentence = f"Topic tagged on the {page}"
    elif relation == "PART_OF":
        kind = str(props.get("relation") or "unknown").replace("_", " ")
        basis = "" if verification == "relation_evidence" else ", relation not verified"
        sentence = f"Conference relation '{kind}' taken from the {page}{basis}"
    elif relation == "LOCATED_AT":
        sentence = f"Venue published on the {page}"
    elif relation == "EXHIBITS_AT":
        sentence = f"Listed as {props.get('role') or 'exhibitor'} on the {page}"
    elif relation == "NEAR" and props.get("distance_m") is not None:
        sentence = f"Distance of {props['distance_m']} m reported by the {page}"
    elif relation == "NEAR":
        modes = sorted(k.removesuffix("_minutes") for k in props if k.endswith("_minutes"))
        providers = sorted({str(props[f"{m}_source"]) for m in modes if props.get(f"{m}_source")})
        sentence = (f"Travel time ({', '.join(modes) or 'unknown mode'}) computed by "
                    f"{', '.join(providers) or 'an unknown provider'}")
    elif relation in {"SERVES_GOAL", "INVOLVES"} and from_kind == "Opportunity":
        sentence = f"Planner agent opportunity built from the {page}"
    elif relation in {"MET", "INVOLVES"} and from_kind == "Meeting":
        sentence = "Meeting reported by the user" + _on(props.get("observed_at") or props.get("at"))
    elif relation == "PLANS" and props.get("state") == "invalidated":
        sentence = f"Removed from the user's plan by {props.get('invalidated_by') or 'an agent'}"
    elif relation == "PLANS":
        sentence = f"In the user's plan, written by {props.get('written_by') or 'an agent'}"
    elif relation == "SKIPS" and props.get("state") == "invalidated":
        sentence = f"Skip withdrawn by {props.get('invalidated_by') or 'an agent'}"
    elif relation == "SKIPS":
        reason = f" ({props['reason']})" if props.get("reason") else ""
        sentence = f"Skipped in the user's plan{reason}, written by {props.get('written_by') or 'an agent'}"
    elif relation == "AFFECTS":
        sentence = f"Plan change written by {props.get('written_by') or 'an agent'} affects this event"
    else:
        sentence = f"{relation} recorded from the {page}"
    if props.get("source_mode") == "fixture":
        sentence = "[fixture] " + sentence
    return sentence


def annotate(relation: str, from_kind: str, from_id: str, props: dict[str, Any]) -> dict[str, Any]:
    """``props`` plus ``rationale`` (unless given) and ``evidence_ids``; refuses no evidence."""
    ids = evidence_ids(from_kind, from_id, props)
    if not ids:
        raise MissingEvidence(
            f"{relation} from {from_kind} {from_id!r}: no evidence id "
            f"(one of {', '.join(EVIDENCE_KEYS)} or evidence_ids)")
    out = {**props, "evidence_ids": ids}
    out.setdefault("rationale", rationale(relation, from_kind, props))
    return out
