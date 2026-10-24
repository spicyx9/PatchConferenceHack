"""Contract checks that every independent feature window must respect."""

from datetime import date, datetime, timezone

import pytest
from pydantic import ValidationError

from conferge.core.schemas import (
    DataEnvelope, DiscoveryQuery, Event, FlightOffer, FlightSegment,
    FlightSlice, Lodging, RunReport, SourceRecord, Venue,
)

NOW = datetime(2026, 10, 23, 23, 0, tzinfo=timezone.utc)


def test_event_needs_evidence_for_confirmed_affiliation():
    with pytest.raises(ValidationError):
        Event(id="evt1", title="Meetup", conference_relation="confirmed_side_event")
    event = Event(
        id="evt1", title="Meetup", conference_relation="confirmed_side_event",
        relation_evidence=["official event mentions GitHub Universe"],
    )
    assert event.conference_relation == "confirmed_side_event"


def test_source_record_requires_aware_time():
    with pytest.raises(ValidationError):
        SourceRecord(provider="luma", source_id="1", source_mode="live",
                     collected_at=datetime(2026, 10, 23))
    record = SourceRecord(provider="luma", source_id="1", source_mode="live",
                          collected_at=NOW, payload={"title": "Example"})
    assert record.as_ref().source_id == "1"


def test_bad_termination_is_never_ok():
    with pytest.raises(ValidationError):
        RunReport(provider="luma", started_at=NOW, finished_at=NOW,
                  status="ok", termination="cursor_stuck", source_mode="live",
                  fetched_count=25, unique_count=20)


def test_unverified_lodging_cannot_claim_bookable():
    with pytest.raises(ValidationError):
        Lodging(id="hotel1", name="Example", provider="booking",
                check_in=date(2026, 10, 27), check_out=date(2026, 10, 30),
                adults=1, price_status="verified_bookable", availability="unknown")


def test_flight_amount_must_be_decimal_string_and_round_trip_two_slices():
    leg = FlightSegment(origin_iata="JFK", destination_iata="SFO", departure_at=NOW)
    back = FlightSegment(origin_iata="SFO", destination_iata="JFK", departure_at=NOW)
    offer = FlightOffer(id="f1", trip_type="round_trip",
                        slices=[FlightSlice(segments=[leg]), FlightSlice(segments=[back])],
                        total_price="399.50", currency="USD", collected_at=NOW,
                        price_status="observed_live")
    assert isinstance(offer.total_price, str)
    with pytest.raises(ValidationError):
        FlightOffer(id="f2", trip_type="one_way", slices=[FlightSlice(segments=[leg])],
                    total_price=399.50, currency="USD", collected_at=NOW)


def test_envelope_preserves_data_provenance():
    value = DataEnvelope[Event](items=[Event(id="e1", title="Test")],
                                source_mode="fixture", status="ok")
    assert value.model_dump(mode="json")["source_mode"] == "fixture"
    assert Venue(latitude=37.8, longitude=-122.4).coordinate_precision == "unknown"


def test_discovery_query_rejects_inverted_dates():
    with pytest.raises(ValidationError):
        DiscoveryQuery(domain="events", start_date=date(2026, 10, 30),
                       end_date=date(2026, 10, 27))
