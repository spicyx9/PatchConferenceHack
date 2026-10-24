"""raidandev.org/vegas/<slug>/ afterparty board parser (independent implementation).

Each event is an <article class="card"> carrying data-day (ISO date or "tba"),
data-type (party, dinner, happy-hour, breakfast, lounge, run...) and
data-invite (rsvp, invite-only, open, badge), then h3 name, p.host, p.meta
("Sun Nov 29 · 7:00 PM - 1:00 AM<br>venue") and RSVP/source links.
A "tba" day stays None. The legacy /vegas/reinvent2026/ path serves the site
home page: that is reported as schema_changed, never as an empty list.
"""

from __future__ import annotations

import html as html_lib
import re
from datetime import date, datetime
from typing import Any

from conferge.core.schemas import SourceMode
from conferge.events.aggregators.common import (
    ParseOutcome,
    make_record,
    rsvp_platform,
    safe_url,
    stable_id,
)

PROVIDER = "raidandev"
BASE_URL = "https://www.raidandev.org/vegas"

_ARTICLE_RE = re.compile(r"<article\b([^>]*)>(.*?)</article>", re.S | re.I)
_ATTR_RE = re.compile(r'([a-zA-Z_:-]+)="([^"]*)"')
_TAG_RE = re.compile(r"<[^>]+>")
_HIDDEN_ADDRESS = re.compile(r"register to see|address hidden|\btba\b", re.IGNORECASE)


def page_url(slug: str) -> str:
    return f"{BASE_URL}/{slug.strip('/')}/"


def _text(fragment: str | None) -> str | None:
    if fragment is None:
        return None
    text = html_lib.unescape(_TAG_RE.sub(" ", fragment))
    text = re.sub(r"\s+", " ", text).strip()
    return text or None


def _first(pattern: str, body: str) -> str | None:
    match = re.search(pattern, body, re.S | re.I)
    return match.group(1) if match else None


def _links(body: str) -> dict[str, str]:
    links: dict[str, str] = {}
    for match in re.finditer(r"<a\b([^>]*)>(.*?)</a>", body, re.S | re.I):
        attrs = dict(_ATTR_RE.findall(match.group(1)))
        href = safe_url(html_lib.unescape(attrs.get("href", "")))
        if not href:
            continue
        css = attrs.get("class", "")
        key = "source_link" if "src" in css.split() else "rsvp_url"
        links.setdefault(key, href)
    return links


def _parse_day(value: str | None) -> date | None:
    if not value or value.lower() == "tba":
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _card_payload(attrs: dict[str, str], body: str) -> dict[str, Any] | None:
    title = _text(_first(r"<h3[^>]*>(.*?)</h3>", body))
    if not title:
        return None
    meta_html = _first(r'<p class="meta"[^>]*>(.*?)</p>', body) or ""
    meta_parts = [_text(part) for part in re.split(r"<br\s*/?>", meta_html, flags=re.I)]
    when_text = meta_parts[0] if meta_parts else None
    location_text = meta_parts[1] if len(meta_parts) > 1 else None
    time_text = None
    if when_text and "·" in when_text:
        time_text = when_text.split("·", 1)[1].strip() or None
    links = _links(body)
    rsvp_url = links.get("rsvp_url")
    chips = [_text(chip) for chip in re.findall(r'<span class="chip[^"]*">(.*?)</span>', body)]
    return {
        "title": title,
        "host": _text(_first(r'<p class="host"[^>]*>(.*?)</p>', body)),
        "event_kind": attrs.get("data-type") or None,
        "access": attrs.get("data-invite") or None,
        "chips": [chip for chip in chips if chip],
        "when_text": when_text,
        "time_text": time_text,
        "location_text": location_text,
        "address_hidden": bool(location_text and _HIDDEN_ADDRESS.search(location_text)),
        "rsvp_url": rsvp_url,
        "rsvp_platform": rsvp_platform(rsvp_url),
        "listing_source_url": links.get("source_link"),
        "day_attr": attrs.get("data-day") or None,
    }


def parse_page(
    html: str, *, slug: str, collected_at: datetime, source_mode: SourceMode,
    url: str | None = None,
) -> ParseOutcome:
    outcome = ParseOutcome()
    url = url or page_url(slug)
    articles = _ARTICLE_RE.findall(html)
    cards = [(dict(_ATTR_RE.findall(head)), body) for head, body in articles]
    cards = [(attrs, body) for attrs, body in cards if "card" in attrs.get("class", "").split()]
    if not cards:
        if "data-day-sec" in html:
            outcome.warnings.append("empty_page")
        else:
            outcome.termination = "schema_changed"
            outcome.errors.append("no event cards found (page layout changed or slug unknown)")
        return outcome
    for index, (attrs, body) in enumerate(cards):
        payload = _card_payload(attrs, body)
        if payload is None:
            outcome.warnings.append(f"card_without_title:{index}")
            continue
        outcome.raw_rows += 1
        day = _parse_day(payload["day_attr"])
        if day is None:
            outcome.warnings.append(f"row_without_day:{payload['title']!r}")
        payload.update({
            "site": PROVIDER, "slug": slug, "page_url": url, "row_index": index,
            "day": day.isoformat() if day else None,
        })
        source_id = f"{slug}:" + stable_id(payload["day"], payload["title"], payload["rsvp_url"])
        outcome.records.append(make_record(
            PROVIDER, source_id, payload, source_mode=source_mode,
            collected_at=collected_at, source_url=url,
        ))
    return outcome
