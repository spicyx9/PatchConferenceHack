from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from conferge.flights.airports import airport_pairs, airports_for, timezone_for
from conferge.flights.dedupe import cheapest, dedupe_offers, group_by_itinerary, is_mergeable
from conferge.flights.normalize import (
    NormalizationError,
    RawOffer,
    RawSegment,
    RawSlice,
    build_offer,
    parse_duration,
    parse_price,
    to_aware,
)

NOW = datetime(2026, 10, 24, 18, 0, tzinfo=timezone.utc)


def _offer(provider="p1", price="412", number_out="ZZ101", dep="2026-10-27T08:00", fare=None):
    return RawOffer(
        provider=provider, trip_type="round_trip", price=price, currency="USD", fare=fare,
        slices=[
            RawSlice([RawSegment("JFK", "SFO", dep, "2026-10-27T11:30", "ZZ", None, number_out)]),
            RawSlice([RawSegment("SFO", "JFK", "2026-10-30T13:00", "2026-10-30T21:35", "ZZ",
                                 None, "ZZ102")]),
        ],
    )


def test_airports_expansion_and_secondary():
    assert airports_for("New York") == ["JFK", "LGA", "EWR"]
    assert airports_for("San Francisco") == ["SFO", "OAK"]
    assert "SJC" in airports_for("sf", include_secondary=True)
    assert airports_for("jfk") == ["JFK"]
    assert len(airport_pairs("NYC", "San Francisco")) == 6
    assert len(airport_pairs("NYC", "San Francisco", include_secondary=True)) == 9
    assert timezone_for("XXX") is None
    with pytest.raises(KeyError):
        airports_for("Atlantis")


@pytest.mark.parametrize("value,expected", [
    ("$1,139", ("1139", "USD", "$1,139")),
    (412, ("412", None, "412")),
    ("389.50", ("389.50", None, "389.50")),
    ("€ 250", ("250", "EUR", "€ 250")),
    ({"amount": "99.9", "currency": "usd"}, ("99.9", "USD", "99.9")),
    (None, (None, None, None)),
    ("Price unavailable", (None, None, "Price unavailable")),
])
def test_parse_price_keeps_strings_and_unknowns(value, expected):
    assert parse_price(value) == expected


def test_to_aware_uses_airport_zone_and_never_naive():
    dep, warning = to_aware("2026-10-27 08:00", "JFK")
    assert warning is None and dep.utcoffset().total_seconds() == -4 * 3600
    assert dep.tzinfo == ZoneInfo("America/New_York")
    unknown, warning = to_aware("2026-10-27 08:00", "XXX")
    assert unknown is None and "timezone_unknown" in warning
    converted, _ = to_aware("2026-10-27T15:00:00Z", "SFO")
    assert converted.hour == 8


def test_parse_duration():
    assert parse_duration("6 hr 15 min") == 375
    assert parse_duration("5h 40m") == 340
    assert parse_duration(90) == 90
    assert parse_duration("soon") is None


def test_build_offer_round_trip_contract():
    offer = build_offer(_offer(), NOW)
    assert offer.trip_type == "round_trip" and len(offer.slices) == 2
    assert offer.total_price == "412" and offer.currency == "USD"
    assert offer.price_status == "observed_live"
    assert offer.slices[0].segments[0].duration_minutes == 390
    assert offer.slices[0].segments[0].connection_type == "unknown"
    assert offer.carry_on_included is None and offer.checked_bags_included is None
    assert any(w.startswith("price_indicative") for w in offer.warnings)
    assert any(w.startswith("baggage_unverified") for w in offer.warnings)


def test_partial_round_trip_is_rejected():
    raw = _offer()
    raw.slices = raw.slices[:1]
    with pytest.raises(NormalizationError, match="partial_roundtrip"):
        build_offer(raw, NOW)


def test_price_without_currency_is_dropped_not_guessed():
    raw = _offer(price="412")
    raw.currency = None
    offer = build_offer(raw, NOW)
    assert offer.total_price is None and offer.price_status == "unknown"
    assert any("currency_unknown" in w for w in offer.warnings)


def test_booking_token_is_never_a_booking_url():
    raw = _offer()
    raw.booking_url, raw.booking_url_type = "WyJDalJJ-booking-token", "google_flights_booking"
    offer = build_offer(raw, NOW)
    assert offer.booking_url is None and offer.booking_url_type == "unknown"


def test_duplicate_physical_flights_group_across_providers():
    a = build_offer(_offer(provider="brightdata", price="412"), NOW)
    b = build_offer(_offer(provider="serpapi", price="405"), NOW)
    other = build_offer(_offer(number_out="ZZ999"), NOW)
    assert a.dedup_key == b.dedup_key and a.id != b.id
    assert other.dedup_key != a.dedup_key
    groups = group_by_itinerary([a, b, other])
    assert sorted(len(v) for v in groups.values()) == [1, 2]
    assert len(dedupe_offers([a, a, b])) == 2
    assert cheapest([a, b, other]).total_price == "405"


def test_missing_flight_number_is_never_merged():
    raw = _offer(number_out=None)
    a = build_offer(raw, NOW)
    b = build_offer(_offer(number_out=None, provider="other"), NOW)
    assert not is_mergeable(a)
    assert len(group_by_itinerary([a, b])) == 2
    assert any("missing_flight_number" in w for w in a.warnings)
