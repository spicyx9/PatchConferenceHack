"""Normalize raw RainFocus catalog items into core Conference/Event/Person/Company.

Rules applied (CLAUDE.md, docs/CONTRACTS.md):
- Times come from the catalog's explicit UTC fields; local wall time is derived with the
  event IANA zone. No time is ever guessed: unparseable values become None plus a warning.
- Official program items get conference_relation="official". Items of type "Social" are
  sponsor or partner evening events that the organizer lists in its own catalog: they are
  kept distinct as "confirmed_side_event" with the catalog listing as evidence.
- A participant is a confirmed_speaker only for the published catalog items where the
  official catalog lists them; this says nothing about attending anything else.
- Missing data stays None or empty. Unpublished items are skipped.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any
from urllib.parse import urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import ValidationError

from conferge.core.schemas import (
    Company,
    Conference,
    Event,
    Person,
    SourceEvidence,
    SourceMode,
    Venue,
)
from conferge.events.official.rainfocus import CATALOG_URL, SPONSOR_URL

CONFERENCE_ID = "github-universe-2026"
PROVIDER = "rainfocus:github-universe-2026"
DEFAULT_TIMEZONE = "America/Los_Angeles"
# The portal declares eventTimeZone "US/Pacific"; store the canonical IANA name.
_TZ_ALIASES = {"US/Pacific": "America/Los_Angeles"}
_SPEAKER_ROLES = {"speaker", "panelist", "moderator", "facilitator", "presenter", "host"}
_SIDE_EVENT_TYPES = {"social"}
_TOPIC_ATTRIBUTES = ("Topic", "Track", "GitHubproduct")
_STREET_RE = re.compile(r"(^|,\s*)\d+\s+\w")
_ROLE_KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    ("founder", ("founder", "co-founder", "cofounder")),
    ("investor", ("investor", "venture", "general partner", "managing partner")),
    ("pm", ("product manager", "product management", "product lead", "head of product",
            "vp of product", "vp, product", "director of product", "product director")),
    ("devrel", ("developer advocate", "developer relations", "devrel", "evangelist")),
    ("executive", ("chief", "ceo", "cto", "cio", "ciso", "coo", "president", "vp",
                   "vice president", "svp", "evp")),
    ("engineer", ("engineer", "developer", "architect", "programmer")),
]


@dataclass
class OfficialCatalog:
    conference: Conference
    events: list[Event] = field(default_factory=list)
    people: list[Person] = field(default_factory=list)
    companies: list[Company] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "unknown"


def company_id(name: str) -> str:
    return f"company:{slugify(name)}"


def html_to_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = re.sub(r"<br\s*/?>|</p>|</li>", "\n", value, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text).strip()
    return text or None


def resolve_timezone(name: str | None) -> ZoneInfo | None:
    if not name or not isinstance(name, str):
        return None
    try:
        return ZoneInfo(_TZ_ALIASES.get(name, name))
    except (ZoneInfoNotFoundError, ValueError):
        return None


def canonical_timezone_name(name: str | None) -> str | None:
    if resolve_timezone(name) is None:
        return None
    return _TZ_ALIASES.get(name or "", name)


def parse_utc(value: Any) -> datetime | None:
    """RainFocus utcStartTime looks like '2026/10/29 19:15:00' (UTC, no offset)."""
    if not isinstance(value, str) or not value.strip():
        return None
    for fmt in ("%Y/%m/%d %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            return datetime.strptime(value.strip(), fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def parse_local(day: Any, clock: Any, tz: ZoneInfo | None) -> datetime | None:
    if tz is None or not isinstance(day, str) or not isinstance(clock, str):
        return None
    try:
        naive = datetime.strptime(f"{day.strip()} {clock.strip()}", "%Y-%m-%d %H:%M")
    except ValueError:
        return None
    return naive.replace(tzinfo=tz)


def _safe_url(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    value = value.strip()
    if not value.lower().startswith(("http://", "https://")):
        if re.match(r"^[\w.-]+\.[a-z]{2,}(/.*)?$", value, re.I):
            value = "https://" + value
        else:
            return None
    parsed = urlparse(value)
    return value if parsed.netloc and " " not in value else None


def _x_handle(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    value = value.strip()
    if "/" in value:
        path = urlparse(value if "://" in value else "https://" + value).path.strip("/")
        value = path.split("/")[0] if path else ""
    value = value.lstrip("@")
    return value if re.fullmatch(r"[A-Za-z0-9_]{1,30}", value) else None


def _domain(value: Any) -> str | None:
    url = _safe_url(value)
    if not url:
        return None
    host = urlparse(url).netloc.lower().split(":")[0]
    return host.removeprefix("www.") or None


def infer_roles(job_title: str | None) -> list[str]:
    """Deterministic keyword mapping of a published job title; empty when unsure."""
    if not job_title:
        return []
    lowered = job_title.lower()
    roles = [
        role for role, keys in _ROLE_KEYWORDS
        if any(re.search(rf"(?<![a-z]){re.escape(k)}(?![a-z])", lowered) for k in keys)
    ]
    if "devrel" in roles and "engineer" in roles:
        roles.remove("engineer")
    return roles


def attribute_values(item: dict[str, Any], attribute_id: str) -> list[str]:
    values: list[str] = []
    for attr in item.get("attributevalues") or []:
        if attr.get("attribute_id") == attribute_id and isinstance(attr.get("value"), str):
            value = attr["value"].strip()
            if value and value not in values:
                values.append(value)
    return values


def split_room(room: str | None, *, side_event: bool) -> Venue | None:
    """'Main Stage @ Festival Pavilion' -> venue Festival Pavilion; social venues keep their
    own name and street address. Nothing is geocoded here."""
    if not room:
        return None
    parts = [p.strip() for p in room.split("@", 1)]
    head = parts[0] or None
    tail = parts[1] if len(parts) == 2 and parts[1] else None
    address = tail if tail and _STREET_RE.search(tail) else None
    if side_event or address:
        name = head
    else:
        name = tail or head
    return Venue(name=name, address=address)


def _evidence(
    *, source_mode: SourceMode, source_url: str, collected_at: datetime, record_id: str | None,
) -> SourceEvidence:
    return SourceEvidence(
        provider=PROVIDER, source_mode=source_mode, source_url=source_url,
        collected_at=collected_at, source_record_id=record_id, confidence=1.0,
    )


def _event_type(session_type: str | None, title: str) -> str:
    kind = (session_type or "").strip().lower()
    if kind in _SIDE_EVENT_TYPES:
        return "meetup" if "meetup" in title.lower() else "party"
    if "after party" in kind or "afterparty" in kind:
        return "party"
    if "workshop" in kind:
        return "workshop"
    if kind in {"special event"}:
        return "other"
    return "session"


def _times(
    item: dict[str, Any], tz: ZoneInfo | None, warnings: list[str], code: str,
) -> list[tuple[str | None, datetime | None, datetime | None, dict[str, Any]]]:
    out = []
    for slot in item.get("times") or []:
        if not isinstance(slot, dict) or slot.get("isHidden") is True:
            continue
        start = parse_utc(slot.get("utcStartTime"))
        end = parse_utc(slot.get("utcEndTime"))
        local_start = parse_local(slot.get("date"), slot.get("startTime"), tz)
        local_end = parse_local(slot.get("endDate") or slot.get("date"), slot.get("endTime"), tz)
        if start is None and slot.get("utcStartTime"):
            warnings.append(f"{code}: unparseable utcStartTime {slot.get('utcStartTime')!r}")
        if start is None:
            start = local_start
        if end is None:
            end = local_end
        if start is not None and local_start is not None and start != local_start:
            warnings.append(f"{code}: local start disagrees with UTC start; UTC kept")
        if tz is not None:
            start = start.astimezone(tz) if start else None
            end = end.astimezone(tz) if end else None
        if start and end and end < start:
            warnings.append(f"{code}: end before start; end dropped")
            end = None
        out.append((slot.get("sessionTimeID"), start, end, slot))
    return out


def normalize_session(
    item: dict[str, Any],
    *,
    collected_at: datetime,
    source_mode: SourceMode,
    timezone_name: str | None = DEFAULT_TIMEZONE,
    source_url: str = CATALOG_URL,
) -> tuple[list[Event], list[Person], list[Company], list[str]]:
    warnings: list[str] = []
    session_id = str(item.get("sessionID") or "")
    code = str(item.get("code") or session_id or "?")
    title = (item.get("title") or "").strip()
    if not session_id or not title:
        return [], [], [], [f"{code}: missing sessionID or title; skipped"]
    if item.get("published") not in (1, 1.0, True, "1", "true"):
        return [], [], [], [f"{code}: unpublished; skipped"]

    tz = resolve_timezone(timezone_name)
    tz_name = canonical_timezone_name(timezone_name)
    if tz is None:
        warnings.append(
            f"{code}: malformed timezone {timezone_name!r}; times kept in UTC, timezone=None"
        )
    session_type = item.get("type") if isinstance(item.get("type"), str) else None
    is_side = (session_type or "").strip().lower() in _SIDE_EVENT_TYPES
    event_type = _event_type(session_type, title)

    tracks = attribute_values(item, "Track")
    single_track = attribute_values(item, "SessionTrackNotMulti")
    if len(tracks) > 1 and len(single_track) != 1:
        warnings.append(f"{code}: ambiguous track {tracks}; all kept as topics, none primary")
    topics: list[str] = []
    for attribute in _TOPIC_ATTRIBUTES:
        for value in attribute_values(item, attribute):
            if value not in topics:
                topics.append(value)

    evidence = _evidence(source_mode=source_mode, source_url=source_url,
                         collected_at=collected_at, record_id=session_id)
    relation = "confirmed_side_event" if is_side else "official"
    relation_evidence = [
        f"Listed as {session_type or 'item'} {code} in the official GitHub Universe 2026 "
        f"catalog ({source_url})"
    ]

    people: list[Person] = []
    companies: list[Company] = []
    speaker_ids: list[str] = []
    for participant in item.get("participants") or []:
        person = _normalize_participant(
            participant, collected_at=collected_at, source_mode=source_mode,
            source_url=source_url, code=code, warnings=warnings,
        )
        if person is None:
            continue
        people.append(person)
        speaker_ids.append(person.id)
        company_name = (participant.get("companyName") or "").strip()
        if company_name:
            companies.append(Company(
                id=company_id(company_name), name=company_name,
                evidence=[_evidence(source_mode=source_mode, source_url=source_url,
                                    collected_at=collected_at,
                                    record_id=str(participant.get("speakerId") or ""))],
            ))
    if not speaker_ids and not is_side:
        warnings.append(f"{code}: no published speakers")

    slots = _times(item, tz, warnings, code)
    if not slots:
        warnings.append(f"{code}: no published time; start_at=None")
        slots = [(None, None, None, {})]
    events: list[Event] = []
    for slot_id, start, end, raw in slots:
        event_id = f"official:{CONFERENCE_ID}:{session_id}"
        if len(slots) > 1 and slot_id:
            event_id += f":{slot_id}"
        capacity = raw.get("capacity")
        try:
            capacity_int = int(capacity) if capacity not in (None, "") else None
        except (TypeError, ValueError):
            capacity_int = None
        room = raw.get("room") or None
        try:
            event = Event(
                id=event_id,
                conference_id=CONFERENCE_ID,
                title=title,
                description=html_to_text(item.get("abstract")),
                event_type=event_type,
                start_at=start,
                end_at=end,
                timezone=tz_name,
                venue=split_room(room, side_event=is_side),
                organizer_names=["GitHub"] if not is_side else [],
                speaker_ids=speaker_ids,
                topics=topics,
                room=room,
                status="scheduled" if start and item.get("status") == "Accepted" else "unknown",
                conference_relation=relation,
                relation_score=1.0,
                relation_evidence=relation_evidence,
                source_url=source_url,
                capacity=capacity_int if capacity_int and capacity_int > 0 else None,
                evidence=[evidence],
            )
        except ValidationError as exc:
            warnings.append(f"{code}: event rejected by schema ({exc.error_count()} errors)")
            continue
        events.append(event)
    event_ids = [e.id for e in events]
    people = [p.model_copy(update={"event_ids": event_ids}) for p in people]
    return events, people, companies, warnings


def _normalize_participant(
    participant: dict[str, Any], *, collected_at: datetime, source_mode: SourceMode,
    source_url: str, code: str, warnings: list[str],
) -> Person | None:
    if not isinstance(participant, dict):
        return None
    speaker_id = str(participant.get("speakerId") or "")
    name = (participant.get("fullName") or "").strip() or " ".join(
        p for p in [(participant.get("firstName") or "").strip(),
                    (participant.get("lastName") or "").strip()] if p
    )
    if not speaker_id or not name:
        warnings.append(f"{code}: participant without id or name skipped")
        return None
    if str(participant.get("published", "true")).lower() in {"false", "0"}:
        warnings.append(f"{code}: unpublished participant skipped")
        return None
    role_text = (participant.get("roles") or "").lower()
    roles_listed = {r.strip() for r in re.split(r"[,;/]", role_text) if r.strip()}
    participation = "confirmed_speaker" if roles_listed & _SPEAKER_ROLES else "unknown"
    company_name = (participant.get("companyName") or "").strip()
    job_title = (participant.get("jobTitle") or "").strip() or None
    try:
        return Person(
            id=f"person:rainfocus:{speaker_id}",
            name=name,
            company_id=company_id(company_name) if company_name else None,
            role=participant.get("roles") or None,
            title=job_title,
            linkedin_url=_safe_url(participant.get("linkedIn")),
            x_handle=_x_handle(participant.get("twitter")),
            bio=html_to_text(participant.get("bio")),
            roles=infer_roles(job_title),
            participation=participation,
            match_confidence=1.0,
            evidence=[_evidence(source_mode=source_mode, source_url=source_url,
                                collected_at=collected_at, record_id=speaker_id)],
        )
    except ValidationError:
        warnings.append(f"{code}: participant {speaker_id} rejected by schema")
        return None


def normalize_exhibitor(
    item: dict[str, Any], *, collected_at: datetime, source_mode: SourceMode,
    source_url: str = SPONSOR_URL,
) -> tuple[Company | None, list[str]]:
    name = (item.get("name") or "").strip()
    exhibitor_id = str(item.get("exhibitorID") or "")
    if not name or not exhibitor_id:
        return None, ["exhibitor without name or id skipped"]
    if item.get("published") not in (1, 1.0, True, "1", "true"):
        return None, [f"exhibitor {name}: unpublished; skipped"]
    categories = ["sponsor"]
    for tier in attribute_values(item, "ExhibitorType"):
        categories.append(f"sponsor_tier:{slugify(tier)}")
    for booth in item.get("booths") or []:
        if isinstance(booth, dict) and booth.get("booth"):
            categories.append(f"booth:{booth['booth']}")
    industries = attribute_values(item, "Industry")
    linkedin = _safe_url(item.get("linkedinLink"))
    try:
        company = Company(
            id=company_id(name), name=name, domain=_domain(item.get("externalLink")),
            linkedin_url=linkedin if linkedin and "linkedin.com" in linkedin else None,
            industry=industries[0] if industries else None,
            categories=categories,
            evidence=[_evidence(source_mode=source_mode, source_url=source_url,
                                collected_at=collected_at, record_id=exhibitor_id)],
        )
    except ValidationError:
        return None, [f"exhibitor {name}: rejected by schema"]
    return company, []


def build_conference(
    *, sponsor_ids: list[str], topics: list[str], collected_at: datetime, source_mode: SourceMode,
) -> Conference:
    """Static facts published on githubuniverse.com (dates, city, venue)."""
    return Conference(
        id=CONFERENCE_ID,
        name="GitHub Universe 2026",
        start_date=date(2026, 10, 28),
        end_date=date(2026, 10, 29),
        city="San Francisco",
        venue_name="Fort Mason Center",
        timezone=DEFAULT_TIMEZONE,
        official_url="https://githubuniverse.com/",
        latitude=37.8060,
        longitude=-122.4320,
        topics=topics,
        sponsor_ids=sponsor_ids,
        evidence=[_evidence(source_mode=source_mode, source_url="https://githubuniverse.com/",
                            collected_at=collected_at, record_id=None)],
    )


def _merge_people(people: list[Person]) -> list[Person]:
    merged: dict[str, Person] = {}
    for person in people:
        existing = merged.get(person.id)
        if existing is None:
            merged[person.id] = person
            continue
        event_ids = existing.event_ids + [e for e in person.event_ids if e not in existing.event_ids]
        participation = ("confirmed_speaker" if "confirmed_speaker" in
                         {existing.participation, person.participation} else existing.participation)
        merged[person.id] = existing.model_copy(
            update={"event_ids": event_ids, "participation": participation}
        )
    return list(merged.values())


def _merge_companies(companies: list[Company]) -> list[Company]:
    merged: dict[str, Company] = {}
    for company in companies:
        existing = merged.get(company.id)
        if existing is None:
            merged[company.id] = company
            continue
        sponsor, other = (company, existing) if "sponsor" in company.categories else (
            existing, company)
        categories = sponsor.categories + [c for c in other.categories
                                           if c not in sponsor.categories]
        merged[company.id] = sponsor.model_copy(update={
            "categories": categories,
            "domain": sponsor.domain or other.domain,
            "industry": sponsor.industry or other.industry,
            "linkedin_url": sponsor.linkedin_url or other.linkedin_url,
            "evidence": sponsor.evidence + other.evidence[:1],
        })
    return list(merged.values())


def normalize_catalog(
    sessions: list[dict[str, Any]],
    exhibitors: list[dict[str, Any]],
    *,
    collected_at: datetime,
    source_mode: SourceMode,
    timezone_name: str | None = DEFAULT_TIMEZONE,
) -> OfficialCatalog:
    events: list[Event] = []
    people: list[Person] = []
    companies: list[Company] = []
    warnings: list[str] = []
    for item in sessions:
        ev, pe, co, wa = normalize_session(item, collected_at=collected_at,
                                           source_mode=source_mode, timezone_name=timezone_name)
        events += ev
        people += pe
        companies += co
        warnings += wa
    sponsor_ids: list[str] = []
    for item in exhibitors:
        company, wa = normalize_exhibitor(item, collected_at=collected_at, source_mode=source_mode)
        warnings += wa
        if company:
            companies.append(company)
            if company.id not in sponsor_ids:
                sponsor_ids.append(company.id)
    topics: list[str] = []
    for event in events:
        if event.conference_relation == "official":
            for topic in event.topics:
                if topic not in topics:
                    topics.append(topic)
    conference = build_conference(sponsor_ids=sponsor_ids, topics=topics,
                                  collected_at=collected_at, source_mode=source_mode)
    return OfficialCatalog(
        conference=conference, events=events, people=_merge_people(people),
        companies=_merge_companies(companies), warnings=warnings,
    )
