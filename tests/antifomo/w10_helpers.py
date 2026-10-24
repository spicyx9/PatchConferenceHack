"""Shared synthetic builders for window 10 tests (not a test module)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from conferge.agents.antifomo.models import Plan
from conferge.agents.antifomo.travel import travel_minutes
from conferge.core.schemas import Event, Venue

PDT = timezone(timedelta(hours=-7))
FORT_MASON = {"name": "Fort Mason Center", "latitude": 37.806, "longitude": -122.432,
              "coordinate_precision": "exact"}
FAR = {"name": "Far Venue", "latitude": 37.760, "longitude": -122.419,
       "coordinate_precision": "approximate"}


def at(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 10, day, hour, minute, tzinfo=PDT)


def ev(event_id: str, start: datetime | None, end: datetime | None, venue: dict | None = None,
       **kw: Any) -> Event:
    data: dict[str, Any] = {
        "id": event_id, "title": f"[Fixture] {event_id}", "start_at": start, "end_at": end,
        "timezone": "America/Los_Angeles",
        "venue": Venue(**(venue if venue is not None else FORT_MASON)),
        "registration_url": "https://example.com/r",
    }
    data.update(kw)
    return Event(**data)


def assert_no_overlap(plan: Plan, events: dict[str, Event], constraints) -> None:
    by_day: dict[str, list] = {}
    for item in plan.items:
        by_day.setdefault(item.day, []).append(item)
    for items in by_day.values():
        items.sort(key=lambda i: i.start_at)
        for prev, cur in zip(items, items[1:], strict=False):
            minutes, _ = travel_minutes(events[prev.event_id], events[cur.event_id], constraints)
            assert prev.end_at + timedelta(minutes=minutes) <= cur.start_at, (prev, cur)
