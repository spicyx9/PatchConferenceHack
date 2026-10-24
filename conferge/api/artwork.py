"""Public event artwork from the explicitly labelled Luma fixture."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from urllib.parse import urlsplit

from conferge.core.schemas import Event

FIXTURE_PATH = Path(__file__).resolve().parents[2] / "fixtures" / "luma.json"


def _safe_cover(value: object) -> str | None:
    if not isinstance(value, str) or any(c.isspace() or ord(c) < 32 for c in value):
        return None
    try:
        url = urlsplit(value)
    except ValueError:
        return None
    if url.scheme != "https" or url.netloc != "images.lumacdn.com" or not url.path:
        return None
    return value


def load_fixture_covers(path: Path | None = None) -> dict[str, str]:
    """Return exact event-id matches; missing or malformed input has no artwork."""
    try:
        raw = json.loads((path or FIXTURE_PATH).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(raw, dict) or raw.get("source_mode") != "fixture":
        return {}
    entries = raw.get("entries")
    if not isinstance(entries, list):
        return {}
    covers: dict[str, str] = {}
    for entry in entries:
        event = entry.get("event") if isinstance(entry, dict) else None
        if not isinstance(event, dict) or event.get("visibility") != "public":
            continue
        api_id = event.get("api_id")
        cover = _safe_cover(event.get("cover_url"))
        if isinstance(api_id, str) and api_id and cover:
            covers.setdefault(f"luma:{api_id}", cover)
    return covers


def event_artwork(event: Event, covers: Mapping[str, str]) -> dict[str, str]:
    """Fixture artwork never implies a live record or an official-session cover."""
    if event.conference_relation == "official" or event.event_type == "session":
        return {}
    if not event.evidence or any(e.source_mode != "fixture" for e in event.evidence):
        return {}
    if not any(e.provider == "luma" for e in event.evidence):
        return {}
    cover = covers.get(event.id)
    return {"cover_url": cover, "cover_source_mode": "fixture"} if cover else {}
