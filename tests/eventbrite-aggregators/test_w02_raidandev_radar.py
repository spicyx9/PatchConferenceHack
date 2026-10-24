"""raidandev.org and reinventradar.com parsers on real captured excerpts."""

from __future__ import annotations

from datetime import date, datetime, timezone

import httpx
from w02_helpers import COLLECTED_AT, assert_report_consistent, read_fixture, static_client

from conferge.core.schemas import DiscoveryQuery
from conferge.events.aggregators import raidandev as rd
from conferge.events.aggregators import reinventradar as rr
from conferge.events.aggregators.normalize import normalize_records
from conferge.events.aggregators.source import AggregatorSource

RD_URL = "https://www.raidandev.org/vegas/reinvent-2026/"
RD_LEGACY_URL = "https://www.raidandev.org/vegas/reinvent2026/"


def _rd(html: str, slug: str = "reinvent-2026"):
    return rd.parse_page(html, slug=slug, collected_at=COLLECTED_AT, source_mode="live")


def test_raidandev_excerpt_parses() -> None:
    outcome = _rd(read_fixture("raidandev_reinvent-2026_excerpt.html"))
    assert outcome.termination == "exhausted"
    assert outcome.errors == []
    assert len(outcome.records) == 5
    titles = [r.payload["title"] for r in outcome.records]
    assert titles[0] == "AWS re:Invent Kickoff Night with HabileLabs"
    first = outcome.records[0].payload
    assert first["day"] == "2026-11-29"
    assert first["time_text"] == "7:00 PM - 1:00 AM"
    assert first["host"] == "HabileLabs"
    assert first["event_kind"] == "party"
    assert first["access"] == "rsvp"
    assert first["rsvp_url"] == "https://luma.com/y4zpryyh"
    assert first["rsvp_platform"] == "luma"
    assert first["listing_source_url"] == "https://conferenceparties.com/reinvent2026/"
    assert first["address_hidden"] is True
    for record in outcome.records:
        assert record.payload["page_url"] == RD_URL
        assert record.collected_at == COLLECTED_AT
        assert record.source_id.startswith("reinvent-2026:")


def test_raidandev_tba_card_day_none() -> None:
    outcome = _rd(read_fixture("raidandev_reinvent-2026_excerpt.html"))
    tba = next(r for r in outcome.records if r.payload["day_attr"] == "tba")
    assert tba.payload["title"] == "Apps Associates Happy Hour"
    assert tba.payload["day"] is None
    assert tba.payload["rsvp_url"] is None  # only a "source" link on that card
    assert tba.payload["rsvp_platform"] is None
    assert any("Apps Associates" in w for w in outcome.warnings)
    events, errors = normalize_records([tba], conference_id="reinvent-2026")
    assert errors == []
    assert events[0].start_at is None and events[0].end_at is None


def test_raidandev_normalized_events() -> None:
    outcome = _rd(read_fixture("raidandev_reinvent-2026_excerpt.html"))
    events, errors = normalize_records(outcome.records, conference_id="reinvent-2026")
    assert errors == []
    kickoff = events[0]
    assert kickoff.start_at is not None and kickoff.start_at.isoformat() == (
        "2026-11-29T19:00:00-08:00"
    )
    assert kickoff.end_at is not None and kickoff.end_at.isoformat() == "2026-11-30T01:00:00-08:00"
    assert kickoff.event_type == "party"
    assert kickoff.venue is not None and kickoff.venue.name is None  # hidden address
    mixer = next(e for e in events if "Mixer" in e.title)
    assert mixer.venue is not None and mixer.venue.name == "SushiSAMBA"
    breakfast = next(e for e in events if "Breakfast" in e.title)
    assert breakfast.event_type == "side_event"
    for event in events:
        assert event.conference_relation == "candidate"
        assert event.relation_evidence == [f"listed_on_aggregator:{RD_URL}"]
        assert event.evidence[0].collected_at == COLLECTED_AT


def test_raidandev_legacy_slug_schema_changed() -> None:
    outcome = _rd(read_fixture("raidandev_legacy_slug_home.html"), "reinvent2026")
    assert outcome.termination == "schema_changed"
    assert outcome.records == []
    assert outcome.errors


def test_raidandev_day_sections_without_cards_empty_page() -> None:
    html = '<main><section class="day" data-day-sec="2026-11-29"><h2>Sun</h2></section></main>'
    outcome = _rd(html)
    assert outcome.termination == "exhausted"
    assert "empty_page" in outcome.warnings


async def test_raidandev_legacy_slug_source_failed() -> None:
    client = static_client(
        {RD_LEGACY_URL: httpx.Response(200, text=read_fixture("raidandev_legacy_slug_home.html"))}
    )
    result = await AggregatorSource("raidandev", "reinvent2026", client=client).discover(
        DiscoveryQuery(domain="events")
    )
    assert result.run_report.status == "failed"
    assert result.run_report.termination == "schema_changed"
    assert result.items == []
    assert result.errors


async def test_raidandev_source_ok() -> None:
    client = static_client(
        {RD_URL: httpx.Response(200, text=read_fixture("raidandev_reinvent-2026_excerpt.html"))}
    )
    result = await AggregatorSource("raidandev", "reinvent-2026", client=client).discover(
        DiscoveryQuery(domain="events")
    )
    assert result.run_report.status == "ok"
    assert result.run_report.provider == "raidandev"
    assert_report_consistent(result.run_report, 5)


def _rr(html: str):
    return rr.parse_page(html, collected_at=COLLECTED_AT, source_mode="live")


def test_reinventradar_four_records() -> None:
    outcome = _rr(read_fixture("reinventradar_schedule_excerpt.html"))
    assert outcome.termination == "exhausted"
    assert len(outcome.records) == 4
    assert [r.source_id for r in outcome.records] == [
        "radar:192", "radar:149", "radar:183", "radar:85",
    ]
    first = outcome.records[0].payload
    assert first["title"] == "Kubernetes Automation Day in Rockhouse"
    assert first["host"] == "KubeAuto Day"
    assert first["start_at_raw"] == "2026-11-29T22:30:00+00:00"
    assert first["rsvp_url"] == "https://kubeauto.day/las-vegas"
    assert any("Darktrace" in w for w in outcome.warnings)


def test_reinventradar_normalized_aware_and_missing_day() -> None:
    outcome = _rr(read_fixture("reinventradar_schedule_excerpt.html"))
    events, errors = normalize_records(outcome.records, conference_id="reinvent-2026")
    assert errors == []
    by_id = {e.id: e for e in events}
    kube = by_id["reinventradar:radar:192"]
    assert kube.start_at is not None and kube.start_at.tzinfo is not None
    assert kube.start_at.isoformat() == "2026-11-29T14:30:00-08:00"
    assert kube.start_at == datetime(2026, 11, 29, 22, 30, tzinfo=timezone.utc)
    assert kube.end_at is not None and kube.end_at.isoformat() == "2026-11-29T19:00:00-08:00"
    assert kube.event_type == "meetup"
    assert kube.topics == ["infra"]
    dinner = by_id["reinventradar:radar:149"]
    assert dinner.event_type == "side_event"
    assert dinner.start_at is not None and dinner.start_at.date() == date(2026, 11, 29)
    dark = by_id["reinventradar:radar:85"]
    assert dark.start_at is None and dark.end_at is None
    for event in events:
        if event.start_at is not None:
            assert event.start_at.tzinfo is not None
        assert event.conference_relation == "candidate"


def test_reinventradar_page_without_events_schema_changed() -> None:
    outcome = _rr("<html><body><h1>The Schedule</h1><script>self.__next_f.push([1,\"0:[]\"])"
                  "</script></body></html>")
    assert outcome.termination == "schema_changed"
    assert outcome.records == []
    assert outcome.errors


def test_reinventradar_events_key_with_non_event_items_ignored() -> None:
    chunk = '{\\"events\\":[{\\"name\\":\\"x\\"}]}'
    outcome = _rr(f'<script>self.__next_f.push([1,"{chunk}"])</script>')
    assert outcome.termination == "schema_changed"


async def test_reinventradar_source_url_and_report() -> None:
    client = static_client(
        {rr.PAGE_URL: httpx.Response(200, text=read_fixture("reinventradar_schedule_excerpt.html"))}
    )
    result = await AggregatorSource("reinventradar", "", client=client).discover(
        DiscoveryQuery(domain="events")
    )
    assert result.run_report.status == "ok"
    assert len(result.items) == 4
    assert_report_consistent(result.run_report, 4)
