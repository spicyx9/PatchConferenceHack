"""conferenceparties.com/<slug>/ table parser (independent implementation).

The page is one TablePress table: day rows hold an h2 such as
"Wednesday - October 28, 2026", header rows name the columns
(Time | Sponsor | Event & RSVP Link | Location | Added or Listed), data rows
follow. Columns are mapped from the header text, days from the h2 text: no
hard-coded calendar, so the same parser serves every conference slug.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from html.parser import HTMLParser
from typing import Any

from conferge.core.schemas import SourceMode
from conferge.events.aggregators.common import (
    MONTHS,
    ParseOutcome,
    make_record,
    rsvp_platform,
    safe_url,
    stable_id,
)

PROVIDER = "conferenceparties"
BASE_URL = "https://conferenceparties.com"

_DAY_RE = re.compile(
    r"(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)?\s*[-,\u2013]?\s*"
    r"([a-z]+)\s+(\d{1,2}),?\s+(\d{4})",
    re.IGNORECASE,
)
_HEADER_KEYS = {
    "time": "time",
    "sponsor": "sponsor",
    "host": "sponsor",
    "event": "event",
    "location": "location",
    "venue": "location",
    "added": "added",
    "listed": "added",
}
_HIDDEN_ADDRESS = re.compile(r"register to see|address hidden|\btba\b", re.IGNORECASE)


def page_url(slug: str) -> str:
    return f"{BASE_URL}/{slug.strip('/')}/"


class _Cell:
    def __init__(self, colspan: int) -> None:
        self.colspan = colspan
        self.parts: list[str] = []
        self.links: list[str] = []
        self.has_h2 = False
        self.h2_parts: list[str] = []
        self.in_tooltip = 0

    @property
    def lines(self) -> list[str]:
        text = "".join(self.parts)
        return [re.sub(r"\s+", " ", line).strip() for line in text.split("\n") if line.strip()]

    @property
    def text(self) -> str:
        return " ".join(self.lines)


class _TableParser(HTMLParser):
    """Collect rows of the first tablepress table; tolerant of unclosed tags."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[_Cell]] = []
        self.table_found = False
        self._depth = 0
        self._row: list[_Cell] | None = None
        self._cell: _Cell | None = None
        self._in_h2 = False
        self._span_stack: list[bool] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = dict(attrs)
        if tag == "table":
            if self._depth == 0 and not self.table_found and "tablepress" in (attr.get("class") or ""):
                self.table_found = True
                self._depth = 1
            elif self._depth:
                self._depth += 1
            return
        if not self._depth:
            return
        if tag == "tr":
            self._close_row()
            self._row = []
        elif tag in {"td", "th"} and self._row is not None:
            self._close_cell()
            try:
                colspan = int(attr.get("colspan") or 1)
            except ValueError:
                colspan = 1
            self._cell = _Cell(colspan)
        elif self._cell is None:
            return
        elif tag == "br":
            self._cell.parts.append("\n")
        elif tag == "h2":
            self._in_h2 = True
            self._cell.has_h2 = True
        elif tag == "a" and attr.get("href"):
            self._cell.links.append(attr["href"] or "")
        elif tag == "span":
            tooltip = "tooltips" in (attr.get("class") or "")
            self._span_stack.append(tooltip)
            if tooltip:
                self._cell.in_tooltip += 1
        elif tag == "img":
            return

    def handle_endtag(self, tag: str) -> None:
        if not self._depth:
            return
        if tag == "table":
            self._depth -= 1
            if self._depth == 0:
                self._close_row()
            return
        if tag == "tr":
            self._close_row()
        elif tag in {"td", "th"}:
            self._close_cell()
        elif tag == "h2":
            self._in_h2 = False
        elif tag == "span" and self._span_stack and self._cell is not None:
            if self._span_stack.pop():
                self._cell.in_tooltip = max(self._cell.in_tooltip - 1, 0)

    def handle_data(self, data: str) -> None:
        if self._cell is None:
            return
        if self._in_h2:
            self._cell.h2_parts.append(data)
        if self._cell.in_tooltip:
            return  # "Request an Invite" button label, not part of the title
        self._cell.parts.append(data)

    def _close_cell(self) -> None:
        if self._cell is not None and self._row is not None:
            self._row.append(self._cell)
        self._cell = None
        self._span_stack = []

    def _close_row(self) -> None:
        self._close_cell()
        if self._row:
            self.rows.append(self._row)
        self._row = None


def parse_day(text: str) -> date | None:
    match = _DAY_RE.search(text or "")
    if not match:
        return None
    month = MONTHS.get(match.group(1).lower())
    if month is None:
        return None
    try:
        return date(int(match.group(3)), month, int(match.group(2)))
    except ValueError:
        return None


def _header_map(cells: list[_Cell]) -> dict[str, int] | None:
    mapping: dict[str, int] = {}
    for index, cell in enumerate(cells):
        label = cell.text.lower()
        for key, field_name in _HEADER_KEYS.items():
            if label.startswith(key) and field_name not in mapping:
                mapping[field_name] = index
                break
    if {"time", "event"} <= mapping.keys():
        return mapping
    return None


def parse_page(
    html: str, *, slug: str, collected_at: datetime, source_mode: SourceMode,
    url: str | None = None,
) -> ParseOutcome:
    """Parse rows into SourceRecords; layout drift yields schema_changed, not guesses."""
    outcome = ParseOutcome()
    url = url or page_url(slug)
    parser = _TableParser()
    parser.feed(html)
    parser.close()
    if not parser.table_found:
        outcome.termination = "schema_changed"
        outcome.errors.append("no tablepress table found on page")
        return outcome

    current_day: date | None = None
    current_heading: str | None = None
    columns: dict[str, int] | None = None
    seen_header = False
    for row_index, cells in enumerate(parser.rows):
        if len(cells) == 1 and cells[0].colspan > 1:
            if cells[0].has_h2:
                current_heading = re.sub(r"\s+", " ", "".join(cells[0].h2_parts)).strip()
                current_day = parse_day(current_heading)
                if current_day is None:
                    outcome.warnings.append(f"day_heading_unparsed:{current_heading!r}")
            continue  # sponsor banners and navigation rows
        header = _header_map(cells)
        if header is not None:
            columns, seen_header = header, True
            continue
        if columns is None or not any(cell.text for cell in cells):
            continue
        record_payload = _row_payload(cells, columns)
        if record_payload is None:
            continue
        outcome.raw_rows += 1
        if current_day is None:
            outcome.warnings.append(f"row_without_day:{record_payload['title']!r}")
        record_payload.update({
            "site": PROVIDER,
            "slug": slug,
            "page_url": url,
            "row_index": row_index,
            "day": current_day.isoformat() if current_day else None,
            "day_heading": current_heading,
        })
        source_id = f"{slug}:" + stable_id(
            record_payload["day"], record_payload["title"], record_payload["rsvp_url"]
        )
        outcome.records.append(make_record(
            PROVIDER, source_id, record_payload, source_mode=source_mode,
            collected_at=collected_at, source_url=url,
        ))
    if not seen_header:
        outcome.termination = "schema_changed"
        outcome.errors.append("table has no Time/Event header row")
    elif not outcome.records:
        outcome.warnings.append("empty_page")
    return outcome


def _cell(cells: list[_Cell], columns: dict[str, int], name: str) -> _Cell | None:
    index = columns.get(name)
    if index is None or index >= len(cells):
        return None
    return cells[index]


def _row_payload(cells: list[_Cell], columns: dict[str, int]) -> dict[str, Any] | None:
    event_cell = _cell(cells, columns, "event")
    if event_cell is None or not event_cell.text:
        return None
    time_cell = _cell(cells, columns, "time")
    sponsor_cell = _cell(cells, columns, "sponsor")
    location_cell = _cell(cells, columns, "location")
    added_cell = _cell(cells, columns, "added")
    rsvp_url = safe_url(event_cell.links[0]) if event_cell.links else None
    location_lines = location_cell.lines if location_cell else []
    address_hidden = bool(location_lines) and bool(_HIDDEN_ADDRESS.search(location_lines[0]))
    return {
        "title": event_cell.text,
        "time_text": time_cell.text if time_cell and time_cell.text else None,
        "sponsor": sponsor_cell.text if sponsor_cell and sponsor_cell.text else None,
        "rsvp_url": rsvp_url,
        "rsvp_platform": rsvp_platform(rsvp_url),
        "location_lines": location_lines,
        "address_hidden": address_hidden,
        "added_text": added_cell.text if added_cell and added_cell.text else None,
    }
