"""RFC 5545 iCalendar export of the current *selected* Conferge plan.

Only times supplied by events are exported. Missing ends remain missing:
we never manufacture a duration, venue, registration or attendee status.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any, Iterable


def _escape(value: str) -> str:
    return (value.replace("\\", "\\\\").replace("\r\n", "\n")
            .replace("\r", "\n").replace("\n", "\\n")
            .replace(";", "\\;").replace(",", "\\,"))


def _fold(line: str) -> list[str]:
    """Fold at 75 *octets*, not characters; never split UTF-8 code points."""
    lines: list[str] = []
    buffer = ""
    byte_size = 0
    for char in line:
        size = len(char.encode("utf-8"))
        if byte_size + size > 75:
            lines.append(buffer)
            buffer, byte_size = " " + char, 1 + size
        else:
            buffer += char
            byte_size += size
    lines.append(buffer)
    return lines


def _utc(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("calendar events require timezone-aware timestamps")
    return value.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _field(event: Any, key: str) -> Any:
    return event.get(key) if isinstance(event, dict) else getattr(event, key, None)


def _as_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def export_plan_ics(
    events: Iterable[Any], selected_ids: set[str], *,
    generated_at: datetime | None = None,
) -> str:
    """Export selected, non-cancelled events with known aware start times."""
    stamp = _utc(generated_at or datetime.now(timezone.utc))
    lines = [
        "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Conferge//Conference Plan//EN",
        "CALSCALE:GREGORIAN", "METHOD:PUBLISH", "X-WR-CALNAME:Conferge plan",
    ]
    included: set[str] = set()
    for event in events:
        event_id = _field(event, "id")
        if not isinstance(event_id, str) or event_id not in selected_ids or event_id in included:
            continue
        if _field(event, "status") in {"cancelled", "sold_out"}:
            continue
        start = _as_datetime(_field(event, "start_at"))
        if not start:
            continue
        end = _as_datetime(_field(event, "end_at"))
        # A missing end is valid in iCalendar, but a contradictory end is not.
        if end and (end.tzinfo is None or end.utcoffset() is None):
            raise ValueError("calendar end must be timezone-aware")
        if end and end < start:
            continue
        uid = hashlib.sha256(event_id.encode("utf-8")).hexdigest()[:24] + "@conferge"
        title = _field(event, "title") or "Conference event"
        lines.extend([
            "BEGIN:VEVENT", f"UID:{uid}", f"DTSTAMP:{stamp}",
            f"DTSTART:{_utc(start)}", f"SUMMARY:{_escape(str(title))}",
        ])
        if end:
            lines.append(f"DTEND:{_utc(end)}")
        venue = _field(event, "venue")
        if venue:
            if isinstance(venue, str):
                location = venue
            else:
                location = ", ".join(str(v) for v in (
                    _field(venue, "name"), _field(venue, "address"), _field(venue, "city")
                ) if v)
            if location:
                lines.append("LOCATION:" + _escape(location))
        description = _field(event, "description")
        if description:
            lines.append("DESCRIPTION:" + _escape(str(description)))
        url = _field(event, "registration_url") or _field(event, "source_url")
        if url and str(url).startswith(("https://", "http://")):
            lines.append("URL:" + str(url))
        lines.append("END:VEVENT")
        included.add(event_id)
    lines.append("END:VCALENDAR")
    return "\r\n".join(part for line in lines for part in _fold(line)) + "\r\n"
