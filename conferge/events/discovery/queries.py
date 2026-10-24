"""Goal- and conference-aware SERP query generation (window 04).

Three families are always produced so the frontier is not limited to pages that
name the conference:
- `conference`: conference name with side-event words;
- `host`: sponsors / hosts / speakers' companies with city and month;
- `venue_date`: city or venue with dates and goal topics, *without* conference keywords
  (side events often never mention the anchor conference);
plus `platform` queries restricted with `site:` to Luma, Partiful, Eventbrite, Meetup,
Facebook events and LinkedIn events.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

QueryFamily = Literal["conference", "host", "venue_date", "platform", "goal"]

SIDE_EVENT_WORDS = ("afterparty", "meetup", "hackathon", "happy hour", "side event")
PLATFORM_SITES = (
    "luma.com", "partiful.com", "eventbrite.com", "meetup.com", "facebook.com/events",
    "linkedin.com/events",
)


class SerpQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    text: str
    family: QueryFamily
    reason: str


class QueryPlan(BaseModel):
    """Inputs for query generation. Every field is optional except the city."""

    model_config = ConfigDict(extra="forbid")

    city: str
    conference_name: str | None = None
    aliases: list[str] = Field(default_factory=list)
    venue: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    sponsors: list[str] = Field(default_factory=list)
    hosts: list[str] = Field(default_factory=list)
    topics: list[str] = Field(default_factory=list)
    max_sponsors: int = Field(default=8, ge=0)
    max_platform_days: int = Field(default=4, ge=0)
    extra_queries: list[str] = Field(default_factory=list)
    """Explicit queries sent first, as written (e.g. the demo's hand-picked searches)."""


def _quote(value: str) -> str:
    value = value.replace('"', "").strip()
    return f'"{value}"' if " " in value else value


def _month_year(day: date | None) -> str:
    return day.strftime("%B %Y") if day else ""


def _day_text(day: date) -> str:
    return f"{day.strftime('%B')} {day.day} {day.year}"


def _window_days(plan: QueryPlan) -> list[date]:
    if not plan.start_date:
        return []
    end = plan.end_date or plan.start_date
    days: list[date] = []
    cursor = plan.start_date - timedelta(days=1)
    while cursor <= end + timedelta(days=1) and len(days) < plan.max_platform_days:
        days.append(cursor)
        cursor += timedelta(days=1)
    return days


def build_queries(plan: QueryPlan) -> list[SerpQuery]:
    """Deterministic, de-duplicated list of SERP queries for one conference plan."""
    city = plan.city.strip()
    month = _month_year(plan.start_date)
    out: list[SerpQuery] = []

    def add(text: str, family: QueryFamily, reason: str) -> None:
        text = " ".join(text.split())
        if text and all(q.text.casefold() != text.casefold() for q in out):
            out.append(SerpQuery(text=text, family=family, reason=reason))

    for text in plan.extra_queries:
        add(text, "conference", "explicit query")
    if plan.conference_name:
        name = _quote(plan.conference_name)
        for word in SIDE_EVENT_WORDS:
            add(f"{name} {city} {word}", "conference", f"conference name + '{word}'")
        add(f"{name} {month} party", "conference", "conference name + month + party")
        for alias in plan.aliases:
            add(f"{_quote(alias)} developer event {city} {month}", "conference",
                f"conference alias '{alias}'")

    seen_hosts: set[str] = set()
    for org in [*plan.hosts, *plan.sponsors[: plan.max_sponsors]]:
        key = org.casefold().strip()
        if not key or key in seen_hosts:
            continue
        seen_hosts.add(key)
        add(f"{_quote(org)} {city} {month} party", "host", f"sponsor/host '{org}' party")
        add(f"{_quote(org)} {city} {month} workshop OR meetup", "host",
            f"sponsor/host '{org}' workshop or meetup")

    # Venue/date queries deliberately omit conference keywords.
    for day in _window_days(plan):
        add(f"{city} tech event {_day_text(day)}", "venue_date",
            f"city + date {day.isoformat()} without conference keywords")
    if plan.venue:
        add(f"{_quote(plan.venue)} {city} event {month}", "venue_date",
            "venue + month without conference keywords")
    for topic in plan.topics:
        add(f"{_quote(topic)} {city} {month} event", "goal", f"goal topic '{topic}'")

    for site in PLATFORM_SITES:
        if site in {"luma.com"}:
            for day in _window_days(plan):
                add(f"site:{site} {city} {_day_text(day)}", "platform",
                    f"site:{site} for {day.isoformat()}")
        else:
            add(f"site:{site} {city} {month} developer OR AI", "platform",
                f"site:{site} for the conference month")
    return out
