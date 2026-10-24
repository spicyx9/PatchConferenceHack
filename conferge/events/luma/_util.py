"""Small helpers private to the Luma adapter (time parsing, geo, hashing)."""

from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json"[^>]*>(.*?)</script>', re.S
)


def content_hash(payload: Any) -> str:
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return "sha256:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()


def parse_instant(value: Any) -> datetime | None:
    """Parse an ISO-8601 instant; naive or unparseable values become None."""
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None  # never substitute a timezone for a naive source time
    return parsed


def zone(name: Any) -> ZoneInfo | None:
    if not isinstance(name, str) or not name:
        return None
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return None


def localize(instant: datetime | None, tz: ZoneInfo | None) -> datetime | None:
    if instant is None:
        return None
    return instant.astimezone(tz) if tz else instant


def local_date(instant: datetime | None, tz: ZoneInfo | None) -> date | None:
    local = localize(instant, tz)
    return local.date() if local else None


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def cents_to_money(cents: Any) -> str | None:
    if isinstance(cents, bool) or not isinstance(cents, int) or cents < 0:
        return None
    return str((Decimal(cents) / 100).quantize(Decimal("0.01")))


def extract_next_data(html: str) -> dict[str, Any] | None:
    match = NEXT_DATA_RE.search(html)
    if not match:
        return None
    try:
        data = json.loads(match.group(1))
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def prosemirror_text(node: Any) -> str:
    """Flatten a ProseMirror document (Luma `description_mirror`) to plain text."""
    if not isinstance(node, dict):
        return ""
    if node.get("type") == "text":
        return str(node.get("text") or "")
    parts = [prosemirror_text(child) for child in node.get("content") or []]
    sep = "\n" if node.get("type") in {"doc", "bullet_list", "ordered_list"} else ""
    text = sep.join(p for p in parts if p) if sep else "".join(parts)
    if node.get("type") in {"paragraph", "heading", "list_item"}:
        return text.strip()
    return text
