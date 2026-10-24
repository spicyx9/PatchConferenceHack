"""Generic Sessionize adapter for official conference agendas.

Sessionize publishes a public JSON API per event at
``https://sessionize.com/api/v2/{endpoint_id}/view/All``. The document holds
``sessions``, ``speakers``, ``rooms``, ``categories`` and ``questions``.

Design notes:

* ``SessionizeSource.discover`` returns one raw ``SourceRecord`` per session and per
  speaker. It never raises on provider errors and never falls back to fixtures;
  failures are reported through ``RunReport`` with ``status="failed"``.
* ``normalize_view_all`` is pure and returns a ``SessionizeParse`` dataclass
  (events, people, warnings). Sessionize ``startsAt``/``endsAt`` values are naive
  local times, so they are only localized when a valid IANA timezone is supplied.
  Without one, ``start_at``/``end_at`` stay ``None``: we never guess.
* The ``discover`` query ``limit`` is intentionally not applied: the endpoint is a
  single complete document and truncating it would misreport completeness.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx
from pydantic import HttpUrl, TypeAdapter, ValidationError

from conferge.core.schemas import (
    DiscoveryQuery,
    DiscoveryResult,
    Event,
    Person,
    RunReport,
    SourceEvidence,
    SourceMode,
    SourceRecord,
    SourceRef,
    Termination,
)

PROVIDER = "sessionize"
API_BASE = "https://sessionize.com/api/v2"
_ENDPOINT_RE = re.compile(r"sessionize\.com/api/v2/([a-z0-9]+)", re.IGNORECASE)
_URL_ADAPTER: TypeAdapter[HttpUrl] = TypeAdapter(HttpUrl)
_X_HOSTS = {"twitter.com", "www.twitter.com", "x.com", "www.x.com", "mobile.twitter.com"}
_X_RESERVED = {"intent", "share", "home", "i", "search", "hashtag"}
_HANDLE_RE = re.compile(r"^[A-Za-z0-9_]{1,15}$")


class SessionizeError(RuntimeError):
    """Raised by ``fetch_details`` when the endpoint itself cannot be read."""


@dataclass
class SessionizeParse:
    """Result of normalizing a Sessionize view/All document."""

    events: list[Event] = field(default_factory=list)
    people: list[Person] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def find_endpoint_ids(html: str) -> list[str]:
    """Return Sessionize API endpoint ids embedded in a page, deduped, in order."""
    seen: dict[str, None] = {}
    for match in _ENDPOINT_RE.finditer(html or ""):
        seen.setdefault(match.group(1).lower(), None)
    return list(seen)


def view_all_url(endpoint_id: str) -> str:
    return f"{API_BASE}/{endpoint_id}/view/All"


def content_hash(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                           default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _safe_url(value: Any) -> HttpUrl | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return _URL_ADAPTER.validate_python(value.strip())
    except ValidationError:
        return None


def _x_handle(url: str) -> str | None:
    try:
        parsed = urlparse(url.strip())
    except ValueError:
        return None
    if (parsed.hostname or "").lower() not in _X_HOSTS:
        return None
    parts = [p for p in parsed.path.split("/") if p]
    if not parts:
        return None
    handle = parts[0].lstrip("@")
    if handle.lower() in _X_RESERVED or not _HANDLE_RE.match(handle):
        return None
    return handle


def _resolve_zone(tz_name: str | None, warnings: list[str]) -> ZoneInfo | None:
    if tz_name is None:
        return None
    try:
        return ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        warnings.append(f"invalid timezone {tz_name!r}; session times left unset")
        return None


def _parse_time(value: Any, zone: ZoneInfo | None, warnings: list[str],
                label: str) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        warnings.append(f"{label}: unparseable time {value!r}")
        return None
    if parsed.tzinfo is not None:
        return parsed
    if zone is None:
        return None
    return parsed.replace(tzinfo=zone)


def _text(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _speaker_name(speaker: dict[str, Any]) -> str | None:
    full = _text(speaker.get("fullName"))
    if full:
        return full
    parts = [_text(speaker.get("firstName")), _text(speaker.get("lastName"))]
    joined = " ".join(p for p in parts if p)
    return joined or None


def normalize_view_all(
    data: dict[str, Any],
    *,
    conference_id: str | None,
    timezone: str | None,
    source_url: str,
    collected_at: datetime,
    source_mode: SourceMode,
    endpoint_id: str | None = None,
) -> SessionizeParse:
    """Normalize a Sessionize view/All document into contract ``Event``/``Person``.

    Event ids are ``sessionize:{prefix}:session:{id}`` where prefix is the
    ``conference_id`` when given, else ``endpoint_id`` when given, else
    ``"sessionize"``. Service sessions (breaks, lunch) get ``event_type="other"``.
    """
    out = SessionizeParse()
    warnings = out.warnings
    zone = _resolve_zone(timezone, warnings)
    tz_label = timezone if zone is not None else None
    prefix = conference_id or endpoint_id or "sessionize"
    endpoint_label = endpoint_id or source_url

    def evidence(record_id: Any) -> list[SourceEvidence]:
        return [SourceEvidence(provider=PROVIDER, source_mode=source_mode,
                               source_url=_safe_url(source_url), collected_at=collected_at,
                               source_record_id=str(record_id))]

    rooms = {str(r.get("id")): _text(r.get("name"))
             for r in data.get("rooms") or [] if isinstance(r, dict)}
    category_items: dict[str, str] = {}
    for cat in data.get("categories") or []:
        if not isinstance(cat, dict):
            continue
        for item in cat.get("items") or []:
            if isinstance(item, dict) and _text(item.get("name")):
                category_items[str(item.get("id"))] = item["name"].strip()

    sessions = [s for s in data.get("sessions") or [] if isinstance(s, dict)]
    speakers = [s for s in data.get("speakers") or [] if isinstance(s, dict)]

    # Resolve named speakers first so events only reference people we emit.
    named: dict[str, str] = {}
    for sp in speakers:
        sid = sp.get("id")
        if sid is None:
            warnings.append("speaker without id skipped")
            continue
        name = _speaker_name(sp)
        if name is None:
            warnings.append(f"speaker {sid}: no name, skipped")
            continue
        named[str(sid)] = name

    event_id_by_session: dict[str, str] = {}
    events_by_speaker: dict[str, list[str]] = {}
    for sess in sessions:
        raw_id = sess.get("id")
        title = _text(sess.get("title"))
        if raw_id is None or title is None:
            warnings.append(f"session {raw_id!r}: missing id or title, skipped")
            continue
        sid = str(raw_id)
        label = f"session {sid}"
        start_at = _parse_time(sess.get("startsAt"), zone, warnings, label)
        end_at = _parse_time(sess.get("endsAt"), zone, warnings, label)
        if start_at and end_at and end_at < start_at:
            warnings.append(f"{label}: endsAt precedes startsAt; end time dropped")
            end_at = None
        topics = [category_items[str(c)] for c in sess.get("categoryItems") or []
                  if str(c) in category_items]
        if sess.get("isServiceSession"):
            event_type = "other"
        elif any("workshop" in t.lower() for t in topics):
            event_type = "workshop"
        else:
            event_type = "session"
        speaker_ids: list[str] = []
        for spk in sess.get("speakers") or []:
            spk_id = str(spk.get("id")) if isinstance(spk, dict) else str(spk)
            if spk_id in named:
                pid = f"person:sessionize:{spk_id}"
                if pid not in speaker_ids:
                    speaker_ids.append(pid)
            else:
                warnings.append(f"{label}: speaker {spk_id} not resolvable, not linked")
        event_id = f"sessionize:{prefix}:session:{sid}"
        relation = "official" if conference_id else "unknown"
        relation_evidence = ([f"listed in Sessionize endpoint {endpoint_label} published by "
                              "organizer"] if conference_id else [])
        room_id = sess.get("roomId")
        try:
            event = Event(
                id=event_id,
                conference_id=conference_id,
                title=title,
                description=_text(sess.get("description")),
                event_type=event_type,
                start_at=start_at,
                end_at=end_at,
                timezone=tz_label,
                speaker_ids=speaker_ids,
                topics=topics,
                room=rooms.get(str(room_id)) if room_id is not None else None,
                status="scheduled" if start_at else "unknown",
                conference_relation=relation,
                relation_evidence=relation_evidence,
                source_url=_safe_url(source_url),
                evidence=evidence(sid),
            )
        except ValidationError as exc:
            warnings.append(f"{label}: invalid event skipped ({exc.error_count()} errors)")
            continue
        out.events.append(event)
        event_id_by_session[sid] = event_id
        for pid in speaker_ids:
            events_by_speaker.setdefault(pid, []).append(event_id)

    for sp in speakers:
        sid = sp.get("id")
        if sid is None or str(sid) not in named:
            continue
        pid = f"person:sessionize:{sid}"
        event_ids = list(events_by_speaker.get(pid, []))
        for sess_ref in sp.get("sessions") or []:
            ref = str(sess_ref.get("id")) if isinstance(sess_ref, dict) else str(sess_ref)
            eid = event_id_by_session.get(ref)
            if eid and eid not in event_ids:
                event_ids.append(eid)
        linkedin = public = None
        x_handle = None
        for link in sp.get("links") or []:
            if not isinstance(link, dict):
                continue
            url = link.get("url")
            kind = str(link.get("linkType") or "").lower()
            safe = _safe_url(url)
            if safe is None:
                continue
            host = (safe.host or "").lower()
            if kind == "twitter" or host in _X_HOSTS:
                x_handle = x_handle or _x_handle(str(url))
            elif kind == "linkedin" or host.endswith("linkedin.com"):
                linkedin = linkedin or safe
            elif public is None and kind in {"blog", "company_website", "other", ""}:
                public = safe
        try:
            person = Person(
                id=pid,
                name=named[str(sid)],
                title=_text(sp.get("tagLine")),
                bio=_text(sp.get("bio")),
                linkedin_url=linkedin,
                public_profile_url=public,
                x_handle=x_handle,
                participation="confirmed_speaker" if event_ids else "unknown",
                event_ids=event_ids,
                evidence=evidence(sid),
            )
        except ValidationError as exc:
            warnings.append(f"speaker {sid}: invalid person skipped ({exc.error_count()} errors)")
            continue
        out.people.append(person)
    return out


class SessionizeSource:
    """Live source for one Sessionize endpoint."""

    provider = PROVIDER

    def __init__(self, endpoint_id: str, *, conference_id: str | None = None,
                 timezone: str | None = None, client: httpx.AsyncClient | None = None):
        self.endpoint_id = endpoint_id
        self.conference_id = conference_id
        self.timezone = timezone
        self._client = client

    @property
    def url(self) -> str:
        return view_all_url(self.endpoint_id)

    async def _get(self) -> httpx.Response:
        if self._client is not None:
            return await self._client.get(self.url)
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
            return await client.get(self.url)

    async def fetch_view_all(self) -> tuple[dict[str, Any] | None, Termination | None, str | None]:
        """Return ``(data, termination, error)``; data is None on failure."""
        try:
            resp = await self._get()
        except httpx.HTTPError as exc:
            return None, "error", f"network error: {type(exc).__name__}"
        if resp.status_code == 429:
            return None, "rate_limited", "HTTP 429"
        if resp.status_code == 403:
            return None, "blocked", "HTTP 403"
        if resp.status_code >= 400:
            return None, "error", f"HTTP {resp.status_code}"
        try:
            data = resp.json()
        except ValueError:
            return None, "schema_changed", "response is not JSON"
        if not isinstance(data, dict) or not isinstance(data.get("sessions"), list):
            return None, "schema_changed", "unexpected JSON shape (no sessions list)"
        return data, None, None

    def _records(self, data: dict[str, Any], collected_at: datetime) -> list[SourceRecord]:
        records: list[SourceRecord] = []
        for kind, key in (("session", "sessions"), ("speaker", "speakers")):
            for raw in data.get(key) or []:
                if not isinstance(raw, dict) or raw.get("id") is None:
                    continue
                records.append(SourceRecord(
                    provider=PROVIDER, source_id=f"{kind}:{raw['id']}", source_mode="live",
                    collected_at=collected_at, payload=raw, source_url=self.url,
                    content_hash=content_hash(raw),
                ))
        return records

    def normalize(self, data: dict[str, Any], collected_at: datetime) -> SessionizeParse:
        return normalize_view_all(
            data, conference_id=self.conference_id, timezone=self.timezone,
            source_url=self.url, collected_at=collected_at, source_mode="live",
            endpoint_id=self.endpoint_id,
        )

    async def discover(self, query: DiscoveryQuery) -> DiscoveryResult:
        started = datetime.now(timezone.utc)
        data, termination, error = await self.fetch_view_all()
        collected = datetime.now(timezone.utc)
        if data is None:
            return self._failed(started, termination or "error", error or "unknown error")
        sessions = [s for s in data["sessions"] if isinstance(s, dict)]
        if not sessions:
            return self._failed(started, "error", "zero sessions")
        records = self._records(data, collected)
        unique = len({r.source_id for r in records})
        report = RunReport(
            provider=PROVIDER, started_at=started, finished_at=datetime.now(timezone.utc),
            status="ok", termination="not_applicable", source_mode="live",
            fetched_count=len(records), unique_count=unique, pages=1,
            warnings=self.normalize(data, collected).warnings,
        )
        return DiscoveryResult(items=records, run_report=report)

    def _failed(self, started: datetime, termination: Termination, error: str) -> DiscoveryResult:
        msg = f"sessionize {self.endpoint_id}: {error}"
        report = RunReport(
            provider=PROVIDER, started_at=started, finished_at=datetime.now(timezone.utc),
            status="failed", termination=termination, source_mode="live",
            fetched_count=0, unique_count=0, pages=0, errors=[msg],
        )
        return DiscoveryResult(items=[], run_report=report, errors=[msg])

    async def fetch_details(self, ref: SourceRef) -> SourceRecord:
        data, _termination, error = await self.fetch_view_all()
        if data is None:
            raise SessionizeError(f"sessionize {self.endpoint_id}: {error}")
        for record in self._records(data, datetime.now(timezone.utc)):
            if record.source_id == ref.source_id:
                return record
        raise LookupError(f"{ref.source_id} not found in sessionize {self.endpoint_id}")
