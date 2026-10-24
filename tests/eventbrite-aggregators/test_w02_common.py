"""Shared aggregator helpers: time ranges, M/D listing dates, RSVP routing, reports."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from conferge.events.aggregators.common import (
    ParseOutcome,
    build_report,
    combine,
    parse_month_day,
    parse_time_range,
    rsvp_platform,
    termination_for_status,
)

LA = ZoneInfo("America/Los_Angeles")
EN = "\u2013"  # en dash, as used by conferenceparties.com


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (f"5:30{EN}7:30PM", (time(17, 30), time(19, 30))),
        (f"7PM{EN}1AM", (time(19, 0), time(1, 0))),
        (f"2:30{EN}7PM", (time(14, 30), time(19, 0))),
        (f"6{EN}10PM", (time(18, 0), time(22, 0))),
        (f"11{EN}1PM", (time(11, 0), time(13, 0))),
        (f"5{EN}8PM", (time(17, 0), time(20, 0))),
        ("7:00 PM - 1:00 AM", (time(19, 0), time(1, 0))),
        ("8:00 AM - 9:00 PM", (time(8, 0), time(21, 0))),
        ("10\u20142AM", (time(22, 0), time(2, 0))),
        ("6pm to 9pm", (time(18, 0), time(21, 0))),
        ("7PM", (time(19, 0), None)),
        ("18:30", (time(18, 30), None)),
    ],
)
def test_parse_time_range(text: str, expected: tuple[time | None, time | None]) -> None:
    assert parse_time_range(text) == expected


@pytest.mark.parametrize(
    "text", [None, "", "TBA", "evening", "all day", "25:00", "13PM", "7:75PM", "5-8 maybe"]
)
def test_parse_time_range_garbage(text: str | None) -> None:
    assert parse_time_range(text) == (None, None)


def test_combine_overnight_rolls_end_to_next_day() -> None:
    start, end = parse_time_range(f"7PM{EN}1AM")
    start_at, end_at = combine(date(2026, 10, 28), start, end, LA)
    assert start_at == datetime(2026, 10, 28, 19, tzinfo=LA)
    assert end_at == datetime(2026, 10, 29, 1, tzinfo=LA)
    assert start_at.tzinfo is not None and end_at > start_at


def test_combine_missing_parts_gives_none() -> None:
    assert combine(None, time(19), None, LA) == (None, None)
    assert combine(date(2026, 10, 28), None, time(20), LA) == (None, None)
    assert combine(date(2026, 10, 28), time(19), None, None) == (None, None)
    start_at, end_at = combine(date(2026, 10, 28), time(19), None, LA)
    assert start_at is not None and end_at is None


def test_parse_month_day_year_rollback() -> None:
    assert parse_month_day("12/20", date(2026, 1, 10)) == date(2025, 12, 20)


def test_parse_month_day_same_year_and_edges() -> None:
    assert parse_month_day("10/18", date(2026, 10, 28)) == date(2026, 10, 18)
    assert parse_month_day("10/28", date(2026, 10, 28)) == date(2026, 10, 28)
    assert parse_month_day(" 9/11 ", date(2026, 11, 29)) == date(2026, 9, 11)
    assert parse_month_day("10/18/25", date(2026, 10, 28)) == date(2025, 10, 18)
    assert parse_month_day("10/18", None) is None
    assert parse_month_day("13/40", date(2026, 10, 28)) is None
    assert parse_month_day("Oct 18", date(2026, 10, 28)) is None
    assert parse_month_day(None, date(2026, 10, 28)) is None


@pytest.mark.parametrize(
    ("url", "platform"),
    [
        ("https://luma.com/git-together", "luma"),
        ("https://lu.ma/abc", "luma"),
        ("https://www.eventbrite.com/e/foo-123", "eventbrite"),
        ("https://eventbrite.com/e/foo-123", "eventbrite"),
        ("https://www.meetup.com/group/events/1/", "meetup"),
        ("https://partiful.com/e/xyz", "partiful"),
        ("https://amplitude.com/2026-10-github-universe#afterparty", "aggregator"),
        ("https://notluma.com/x", "aggregator"),
        ("https://luma.com.evil.example/x", "aggregator"),
        (None, None),
        ("", None),
    ],
)
def test_rsvp_platform_routing(url: str | None, platform: str | None) -> None:
    assert rsvp_platform(url) == platform


@pytest.mark.parametrize(
    ("code", "termination"), [(401, "blocked"), (403, "blocked"), (429, "rate_limited"),
                              (404, "error"), (500, "error")],
)
def test_termination_for_status(code: int, termination: str) -> None:
    assert termination_for_status(code) == termination


def test_build_report_failed_when_incomplete_and_empty() -> None:
    started = datetime.now(timezone.utc) - timedelta(seconds=1)
    outcome = ParseOutcome(termination="schema_changed", errors=["x"])
    report = build_report("p", started, outcome, source_mode="live", pages=1)
    assert report.status == "failed" and report.termination == "schema_changed"
    assert report.unique_count == 0 and report.fetched_count == 0


def test_build_report_empty_exhausted_is_degraded_unless_ok_on_empty() -> None:
    started = datetime.now(timezone.utc)
    outcome = ParseOutcome()
    assert build_report("p", started, outcome, source_mode="live", pages=1).status == "degraded"
    assert build_report(
        "p", started, outcome, source_mode="live", pages=1, ok_on_empty=True
    ).status == "ok"
