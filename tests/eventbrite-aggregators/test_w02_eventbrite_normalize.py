"""Eventbrite destination_event payload -> Event normalization on real captured results."""

from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from w02_helpers import COLLECTED_AT, real_results

from conferge.core.schemas import SourceRecord
from conferge.events.eventbrite.normalize import local_datetime, normalize_record, normalize_records


def _record(item: dict[str, Any], mode: str = "live") -> SourceRecord:
    return SourceRecord(
        provider="eventbrite", source_id=str(item["id"]), source_mode=mode,
        collected_at=COLLECTED_AT, payload=item, source_url=item.get("url"),
    )


def _first() -> dict[str, Any]:
    return copy.deepcopy(real_results()[0])


def test_real_result_full_mapping() -> None:
    event = normalize_record(_record(_first()))
    assert event.id == "eventbrite:1984404755041"
    assert event.title == "TRIVIA with Oakland's Finest Trivia"
    assert event.timezone == "America/Los_Angeles"
    assert event.start_at is not None and event.start_at.tzinfo is not None
    assert event.start_at.isoformat() == "2026-10-28T19:00:00-07:00"
    assert event.end_at is not None
    assert event.end_at.isoformat() == "2026-10-28T21:00:00-07:00"
    assert event.start_at.astimezone(timezone.utc) == datetime(2026, 10, 29, 2, tzinfo=timezone.utc)
    venue = event.venue
    assert venue is not None
    assert venue.name == "Original Pattern Brewing"
    assert venue.address == "292 4th St, Oakland, CA 94607"
    assert venue.city == "Oakland"
    assert venue.latitude == 37.7961351
    assert venue.longitude == -122.27145889999997
    assert venue.coordinate_precision == "exact"
    assert event.price_min == "0.00" and event.price_max == "0.00"
    assert isinstance(event.price_min, str)
    assert event.currency == "USD"
    assert event.is_free is True
    assert event.organizer_names == ["Original Pattern Brewing"]
    assert event.organizer_ids == ["eventbrite-organizer:16482971751"]
    assert event.status == "scheduled"
    assert event.event_type == "party"
    assert event.topics == ["Beer", "Food & Drink"]
    assert event.conference_relation == "unknown"
    assert str(event.source_url) == real_results()[0]["url"]
    assert event.first_listed_at == datetime(2026, 3, 3, 18, 56, 21, tzinfo=timezone.utc)
    assert len(event.evidence) == 1
    ev = event.evidence[0]
    assert ev.provider == "eventbrite" and ev.source_mode == "live"
    assert ev.collected_at == COLLECTED_AT


def test_second_real_result_organizer_without_name() -> None:
    event = normalize_record(_record(copy.deepcopy(real_results()[1])))
    assert event.organizer_names == []
    assert event.organizer_ids == ["eventbrite-organizer:118898869541"]
    assert event.venue is not None and event.venue.name == "Golden Ratio"
    assert event.venue.latitude == 37.8052081 and event.venue.longitude == -122.2694506
    assert event.end_at is not None and event.end_at.isoformat() == "2026-10-28T23:59:00-07:00"


def test_paid_price_strings_preserved() -> None:
    item = _first()
    ta = item["ticket_availability"]
    ta["minimum_ticket_price"]["major_value"] = "25.00"
    ta["maximum_ticket_price"]["major_value"] = "125.5"
    ta["is_free"] = False
    event = normalize_record(_record(item))
    assert (event.price_min, event.price_max, event.currency) == ("25.00", "125.5", "USD")
    assert event.is_free is False


def test_missing_prices_give_none_currency() -> None:
    item = _first()
    item["ticket_availability"] = {"is_free": None}
    event = normalize_record(_record(item))
    assert event.price_min is None and event.price_max is None
    assert event.currency is None
    assert event.is_free is None


@pytest.mark.parametrize("bad", ["-5.00", "abc", "1.123456", "NaN"])
def test_invalid_money_dropped_not_invented(bad: str) -> None:
    item = _first()
    item["ticket_availability"]["minimum_ticket_price"]["major_value"] = bad
    event = normalize_record(_record(item))
    assert event.price_min is None
    assert event.price_max == "0.00"


def test_hide_start_date_gives_none() -> None:
    item = _first()
    item["hide_start_date"] = True
    event = normalize_record(_record(item))
    assert event.start_at is None


@pytest.mark.parametrize("field", ["start_date", "start_time"])
def test_missing_start_never_today(field: str) -> None:
    item = _first()
    item[field] = None
    event = normalize_record(_record(item))
    assert event.start_at is None  # never substituted with today's date


def test_missing_timezone_gives_no_datetimes() -> None:
    item = _first()
    item["timezone"] = None
    event = normalize_record(_record(item))
    assert event.start_at is None and event.end_at is None and event.timezone is None


def test_end_before_start_dropped() -> None:
    item = _first()
    item["end_time"] = "18:00"
    event = normalize_record(_record(item))
    assert event.start_at is not None
    assert event.end_at is None


def test_cancelled_status() -> None:
    item = _first()
    item["is_cancelled"] = True
    item["ticket_availability"]["is_sold_out"] = True
    assert normalize_record(_record(item)).status == "cancelled"


def test_sold_out_status() -> None:
    item = _first()
    item["ticket_availability"]["is_sold_out"] = True
    assert normalize_record(_record(item)).status == "sold_out"


def test_online_event_has_no_venue() -> None:
    item = _first()
    item["is_online_event"] = True
    assert normalize_record(_record(item)).venue is None


def test_invalid_coordinates_not_exact() -> None:
    item = _first()
    item["primary_venue"]["address"]["latitude"] = "123.0"
    event = normalize_record(_record(item))
    assert event.venue is not None
    assert event.venue.latitude is None and event.venue.longitude is None
    assert event.venue.coordinate_precision == "unknown"


def test_local_datetime_handles_dst() -> None:
    from zoneinfo import ZoneInfo

    zone = ZoneInfo("America/Los_Angeles")
    before = local_datetime("2026-10-31", "19:00", zone)
    after = local_datetime("2026-11-02", "19:00", zone)
    assert before is not None and after is not None
    assert before.utcoffset() == timedelta(hours=-7)
    assert after.utcoffset() == timedelta(hours=-8)
    assert local_datetime("2026-10-31", None, zone) is None
    assert local_datetime("garbage", "19:00", zone) is None


def test_normalize_records_reports_failures() -> None:
    good = _record(_first())
    bad_item = _first()
    bad_item["id"] = "bad1"
    bad_item["ticket_availability"]["minimum_ticket_price"]["currency"] = "usd"
    events, errors = normalize_records([good, _record(bad_item)])
    assert len(events) == 1
    assert len(errors) == 1 and "bad1" in errors[0]
