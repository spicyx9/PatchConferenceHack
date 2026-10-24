"""conferenceparties.com table parser on the real github26 / reinvent2026 snapshots."""

from __future__ import annotations

from datetime import date, datetime

import httpx
from w02_helpers import COLLECTED_AT, assert_report_consistent, read_fixture, static_client

from conferge.core.schemas import DiscoveryQuery
from conferge.events.aggregators import conferenceparties as cp
from conferge.events.aggregators.normalize import normalize_records
from conferge.events.aggregators.source import AggregatorSource

GH_URL = "https://conferenceparties.com/github26/"


def _parse(html: str, slug: str = "github26"):
    return cp.parse_page(html, slug=slug, collected_at=COLLECTED_AT, source_mode="live")


def _by_title(outcome, fragment: str):
    matches = [r for r in outcome.records if fragment in r.payload["title"]]
    assert len(matches) == 1, [r.payload["title"] for r in outcome.records]
    return matches[0]


def _table(rows: str) -> str:
    return f'<html><body><table class="tablepress tablepress-id-1"><tbody>{rows}</tbody></table>'


HEADER = (
    "<tr><td><b>Time</b></td><td><b>Sponsor</b></td><td><b>Event &amp; RSVP Link</b></td>"
    "<td><b>Location</b></td><td><b>Added</b></td></tr>"
)
DAY = '<tr><td colspan="5"><h2>Wednesday - October 28, 2026</h2></td></tr>'
ROW = (
    "<tr><td>6\u20139PM</td><td>Acme &amp; Beta</td>"
    '<td><a href="https://lu.ma/acme">Acme Mixer<br>'
    "<span class='tooltipsall'>Request an Invite</span></a></td>"
    "<td>The Bar<br>1 Main St</td><td>10/20</td></tr>"
)


def test_github26_snapshot_seven_records() -> None:
    outcome = _parse(read_fixture("conferenceparties_github26.html"))
    assert outcome.termination == "exhausted"
    assert outcome.errors == []
    assert len(outcome.records) == 7
    assert outcome.raw_rows == 7
    assert len({r.source_id for r in outcome.records}) == 7
    for record in outcome.records:
        p = record.payload
        assert p["day"] == "2026-10-28"
        assert p["day_heading"] == "Wednesday - October 28, 2026"
        assert "Request an Invite" not in p["title"]
        assert p["added_text"] is not None  # "Listed" column mapped to added
        assert p["page_url"] == GH_URL
        assert str(record.source_url) == GH_URL
        assert record.collected_at == COLLECTED_AT
        assert record.source_mode == "live"
        assert record.provider == "conferenceparties"
        assert record.source_id.startswith("github26:")


def test_github26_field_mapping() -> None:
    outcome = _parse(read_fixture("conferenceparties_github26.html"))
    first = _by_title(outcome, "Ship It Afterparty").payload
    assert first["title"] == "Ship It Afterparty"
    assert first["time_text"] == "5\u20138PM"
    assert first["sponsor"] == "Amplitude"
    assert first["rsvp_url"] == "https://amplitude.com/2026-10-github-universe#afterparty"
    assert first["rsvp_platform"] == "aggregator"
    assert first["location_lines"] == ["Left Door", "1905 Union St"]
    assert first["address_hidden"] is False
    assert first["added_text"] == "10/18"

    hidden = _by_title(outcome, "NeuBird").payload
    assert hidden["address_hidden"] is True
    assert hidden["sponsor"] == "NeuBird & FluidCloud"

    luma = _by_title(outcome, "DevOps on Draft").payload
    assert luma["rsvp_url"] == "https://luma.com/git-together"
    assert luma["rsvp_platform"] == "luma"


def test_github26_normalized_events() -> None:
    outcome = _parse(read_fixture("conferenceparties_github26.html"))
    events, errors = normalize_records(outcome.records, conference_id="github-universe-2026")
    assert errors == []
    assert len(events) == 7
    by_title = {e.title: e for e in events}
    ship = by_title["Ship It Afterparty"]
    assert ship.start_at is not None and ship.start_at.isoformat() == "2026-10-28T17:00:00-07:00"
    assert ship.end_at is not None and ship.end_at.isoformat() == "2026-10-28T20:00:00-07:00"
    assert ship.timezone == "America/Los_Angeles"
    assert ship.venue is not None
    assert (ship.venue.name, ship.venue.address, ship.venue.city) == (
        "Left Door", "1905 Union St", "San Francisco",
    )
    assert ship.organizer_names == ["Amplitude"]
    assert ship.first_listed_at is not None
    assert ship.first_listed_at.isoformat() == "2026-10-18T00:00:00-07:00"
    assert ship.price_min is None and ship.is_free is None  # never invented
    hidden = by_title["NeuBird & FluidCloud Happy Hour"]
    assert hidden.venue is not None and hidden.venue.name is None and hidden.venue.address is None
    assert hidden.organizer_names == ["NeuBird", "FluidCloud"]
    for event in events:
        assert event.conference_relation == "candidate"
        assert event.relation_evidence == [f"listed_on_aggregator:{GH_URL}"]
        assert event.start_at is not None and event.start_at.tzinfo is not None
        assert event.first_listed_at is not None and event.first_listed_at.tzinfo is not None
        assert event.evidence and event.evidence[0].source_mode == "live"
        assert event.evidence[0].collected_at == COLLECTED_AT


def test_reinvent2026_excerpt_with_unclosed_tags_and_overnight() -> None:
    outcome = _parse(read_fixture("conferenceparties_reinvent2026_excerpt.html"), "reinvent2026")
    assert outcome.termination == "exhausted"
    assert len(outcome.records) == 5
    assert all(r.payload["day"] == "2026-11-29" for r in outcome.records)
    assert all(r.payload["added_text"] for r in outcome.records)  # "Added" header
    dinner = _by_title(outcome, "FinOps Leaders Dinner").payload
    assert dinner["sponsor"] == "ProsperOps & Flexera"
    assert dinner["time_text"] == "5:30\u20138PM"
    events, errors = normalize_records(outcome.records, conference_id="reinvent-2026")
    assert errors == []
    kickoff = next(e for e in events if "HabileLabs" in e.title)
    assert kickoff.start_at is not None and kickoff.end_at is not None
    assert kickoff.end_at.date() == date(2026, 11, 30)
    assert kickoff.start_at.utcoffset() is not None
    assert kickoff.first_listed_at is not None
    assert kickoff.first_listed_at.date() == date(2026, 9, 11)


def test_no_tablepress_table_schema_changed() -> None:
    html = "<html><body><table class='other'><tr><td>Time</td><td>Event</td></tr></table>"
    outcome = _parse(html)
    assert outcome.termination == "schema_changed"
    assert outcome.records == [] and outcome.errors


def test_table_without_header_schema_changed() -> None:
    outcome = _parse(_table(DAY + ROW))
    assert outcome.termination == "schema_changed"
    assert outcome.records == []
    assert any("header" in e for e in outcome.errors)


def test_header_without_rows_empty_page() -> None:
    outcome = _parse(_table(DAY + HEADER + "<tr><td></td><td></td><td></td><td></td><td></td></tr>"))
    assert outcome.termination == "exhausted"
    assert outcome.records == []
    assert "empty_page" in outcome.warnings
    assert outcome.errors == []


async def test_header_without_rows_source_reports_ok_exhausted() -> None:
    html = _table(DAY + HEADER)
    client = static_client({GH_URL: httpx.Response(200, text=html)})
    result = await AggregatorSource("conferenceparties", "github26", client=client).discover(
        DiscoveryQuery(domain="events")
    )
    report = result.run_report
    assert report.status == "ok"
    assert report.termination == "exhausted"
    assert result.items == []
    assert "empty_page" in report.warnings
    assert report.pages == 1
    assert_report_consistent(report, 0)


def test_row_before_any_day_heading_has_no_day() -> None:
    outcome = _parse(_table(HEADER + ROW))
    assert len(outcome.records) == 1
    record = outcome.records[0]
    assert record.payload["day"] is None
    assert any(w.startswith("row_without_day") for w in outcome.warnings)
    events, errors = normalize_records(outcome.records, conference_id="github-universe-2026")
    assert errors == []
    assert events[0].start_at is None and events[0].end_at is None
    assert events[0].first_listed_at is None  # no reference year for "10/20"


def test_unparsed_day_heading_warns_and_leaves_day_none() -> None:
    heading = '<tr><td colspan="5"><h2>Sometime soon</h2></td></tr>'
    outcome = _parse(_table(heading + HEADER + ROW))
    assert outcome.records[0].payload["day"] is None
    assert any(w.startswith("day_heading_unparsed") for w in outcome.warnings)


def test_column_reorder_header_driven() -> None:
    header = (
        "<tr><td>Event &amp; RSVP Link</td><td>Listed</td><td>Venue</td>"
        "<td>Host</td><td>Time</td></tr>"
    )
    row = (
        '<tr><td><a href="https://partiful.com/e/1">Rooftop Party</a></td><td>10/2</td>'
        "<td>Register to See Address</td><td>Gamma, Delta</td><td>7PM\u20131AM</td></tr>"
    )
    outcome = _parse(_table(DAY + header + row))
    assert outcome.termination == "exhausted"
    assert len(outcome.records) == 1
    p = outcome.records[0].payload
    assert p["title"] == "Rooftop Party"
    assert p["time_text"] == "7PM\u20131AM"
    assert p["sponsor"] == "Gamma, Delta"
    assert p["added_text"] == "10/2"
    assert p["address_hidden"] is True
    assert p["rsvp_platform"] == "partiful"
    event = normalize_records(outcome.records, conference_id="c")[0][0]
    assert event.start_at == datetime.fromisoformat("2026-10-28T19:00:00-07:00")
    assert event.end_at == datetime.fromisoformat("2026-10-29T01:00:00-07:00")


def test_multiple_days_tracked_from_headings() -> None:
    day2 = '<tr><td colspan="5"><h2>Thursday - October 29, 2026</h2></td></tr>'
    row2 = ROW.replace("Acme Mixer", "Second Night")
    outcome = _parse(_table(DAY + HEADER + ROW + day2 + HEADER + row2))
    days = {r.payload["title"]: r.payload["day"] for r in outcome.records}
    assert days == {"Acme Mixer": "2026-10-28", "Second Night": "2026-10-29"}


def test_unknown_slug_without_timezone_keeps_times_none() -> None:
    outcome = cp.parse_page(
        _table(DAY + HEADER + ROW), slug="unknown-conf", collected_at=COLLECTED_AT,
        source_mode="live",
    )
    events, _ = normalize_records(outcome.records)
    assert events[0].start_at is None and events[0].timezone is None
    events_tz, _ = normalize_records(outcome.records, timezone_name="America/New_York")
    assert events_tz[0].start_at is not None
    assert events_tz[0].start_at.isoformat() == "2026-10-28T18:00:00-04:00"


def test_parse_day_variants() -> None:
    assert cp.parse_day("Wednesday - October 28, 2026") == date(2026, 10, 28)
    assert cp.parse_day("Sunday - November 29, 2026") == date(2026, 11, 29)
    assert cp.parse_day("Thu, Oct 29 2026") == date(2026, 10, 29)
    assert cp.parse_day("Date TBA") is None
    assert cp.parse_day("Smarch 3, 2026") is None
