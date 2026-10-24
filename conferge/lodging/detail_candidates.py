"""Collect documented URL-only discovery responses before normalizing cards."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

from conferge.core.brightdata import BrightDataError
from conferge.lodging._bd import collect


def _identity(row: dict[str, Any], site: str) -> str | None:
    value = row.get("url") or row.get("final_url")
    if not isinstance(value, str):
        return None
    try:
        parsed = urlsplit(value)
        if (
            parsed.scheme != "https"
            or parsed.username
            or parsed.hostname not in {site + ".com", "www." + site + ".com"}
        ):
            return None
        path = parsed.path.rstrip("/")
        if site == "airbnb" and path.startswith("/rooms/"):
            room = path.split("/")[2]
            return room if room.isdigit() else None
        if site == "google" and path.startswith("/travel/hotels/"):
            return path
    except (ValueError, IndexError):
        pass
    return None


async def hydrate(
    rows: list[dict[str, Any]],
    *,
    client: Any,
    dataset: str,
    site: str,
    limit: int,
    country: str,
    poll_interval: float,
    max_wait: float,
    url_for: Any = None,
) -> tuple[list[dict[str, Any]], list[str], bool, int]:
    name_key = "name" if site == "airbnb" else "hotel_name"
    full, candidates = [], {}
    for row in rows:
        if row.get(name_key) or (site == "airbnb" and row.get("listing_title")):
            full.append(row)
            continue
        identity = _identity(row, site)
        if identity:
            candidates.setdefault(identity, row)
        else:
            full.append(row)  # the source adapter reports malformed rows
    if not candidates:
        return rows, [], False, 0
    warnings = []
    if len(candidates) > limit:
        warnings.append(f"detail collection capped at {limit} of {len(candidates)} candidates")
    selected = dict(list(candidates.items())[:limit])
    inputs = [
        {"url": url_for(key) if url_for else row["url"], "country": country}
        for key, row in selected.items()
    ]
    try:
        got = await collect(
            client,
            dataset,
            inputs,
            method="collect_by_url",
            limit_per_input=None,
            poll_interval=poll_interval,
            max_wait=max_wait,
        )
    except BrightDataError as exc:
        return full, [*warnings, f"detail collection failed: {type(exc).__name__}"], True, 1
    matched = set()
    for detail in got.rows:
        identity = (
            str(detail["property_id"])
            if site == "airbnb" and detail.get("property_id")
            else _identity(detail, site)
        )
        if identity not in selected or identity in matched:
            continue
        if not detail.get(name_key) and not (site == "airbnb" and detail.get("listing_title")):
            continue
        matched.add(identity)
        full.append({**selected[identity], **detail, "_detail_snapshot_id": got.snapshot_id})
    missing = len(selected) - len(matched)
    if missing:
        warnings.append(f"{missing} candidate(s) without matching details; not normalized")
    return (
        full,
        [*warnings, *got.warnings],
        bool(missing or got.error_rows or len(candidates) > limit),
        1,
    )
