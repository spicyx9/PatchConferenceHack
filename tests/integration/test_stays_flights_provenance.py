"""Tier ordering, cross-provider dedupe and source counts for live stays and flights."""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from conferge.core.schemas import FlightOffer, Lodging, SourceEvidence, Venue
from conferge.integration.stays_flights import (
    ADULTS,
    STAY_LIMIT,
    dedupe_flights,
    pick_flights,
    pick_stays,
    source_counts,
)

NOW = datetime(2026, 10, 24, 17, 21, tzinfo=timezone.utc)
BOOKING = "Bright Data dataset gd_m4bf7a917zfezv9d5 (Booking)"


def _ev(provider: str, raw_ref: str | None) -> list[SourceEvidence]:
    return [SourceEvidence(provider=provider, source_mode="live", collected_at=NOW,
                           raw_ref=raw_ref, source_record_id="r1")]


def _stay(sid: str, provider: str, raw_ref: str | None, name: str,
          address: str | None = None, city: str | None = "San Francisco") -> Lodging:
    return Lodging(
        id=f"{provider}:{sid}", provider=provider, name=name, total_price=Decimal("800.00"),
        currency="USD", price_status="quoted_total", check_in=date(2026, 10, 27),
        check_out=date(2026, 10, 30), adults=ADULTS, evidence=_ev(provider, raw_ref),
        venue=Venue(name=name, address=address, city=city),
    )


def test_stays_ordered_by_tier_and_deduped_on_name_and_address() -> None:
    stays = [
        _stay("1", "airbnb", None, "Sunny Marina Loft", "1 Bay St"),               # tier 2
        _stay("2", "unlocker", "unlocker:web_unlocker1:hilton",
              "Hilton San Francisco Union Square", None),                           # tier 1
        _stay("3", "booking", "s_snap", "Hilton San Francisco Union Square",
              "333 O'Farrell St, San Francisco"),                                   # tier 0
        _stay("4", "booking", "s_snap", "Hotel Zephyr", "250 Beach St."),            # tier 0
        _stay("5", "google_hotels", "s_gh", "hotel zephyr", "250  beach st"),       # dup of 4
        _stay("6", "booking", "s_snap", "Hotel Zephyr", "1 Other Rd"),               # other address
    ]
    kept = pick_stays(stays)
    assert [s.id for s in kept] == ["booking:3", "booking:4", "booking:6", "airbnb:1"]
    assert source_counts(kept) == f"{BOOKING} x3, Fallback pyairbnb x1"


def test_stays_name_match_needs_same_city_when_address_missing() -> None:
    a = _stay("1", "booking", "s1", "The Marker", "501 Geary St", "San Francisco")
    b = _stay("2", "unlocker", "unlocker:z:marriott", "The Marker", None, "Oakland")
    assert len(pick_stays([b, a])) == 2


def test_stays_limit() -> None:
    stays = [_stay(str(i), "booking", "s", f"Hotel {i}", f"{i} Market St") for i in range(9)]
    assert len(pick_stays(stays)) == STAY_LIMIT == 6


def _one_way(fid: str, provider: str, raw_ref: str | None, origin: str, dest: str, day: int,
             price: str, number: str | None = None, carrier: str | None = "United") -> FlightOffer:
    dep = datetime(2026, 10, day, 15, 0, tzinfo=timezone.utc)
    return FlightOffer.model_validate({
        "id": fid, "trip_type": "one_way", "collected_at": NOW,
        "evidence": _ev(provider, raw_ref), "total_price": price, "currency": "USD",
        "price_status": "observed_live",
        "slices": [{"segments": [{"origin_iata": origin, "destination_iata": dest,
                                  "departure_at": dep.isoformat(), "flight_number": number,
                                  "marketing_carrier": carrier}]}],
    })


BD = ("brightdata_google_flights", "s_flt")
UN = ("brightdata_unlocker_google_flights", "unlocker:web_unlocker1:google_flights")
FF = ("fast_flights_google_flights", None)


def test_pick_flights_prefers_dataset_tier_over_cheaper_fallback() -> None:
    offers = [
        _one_way("ff-out", *FF, "JFK", "SFO", 27, "199", carrier="Delta"),
        _one_way("ff-back", *FF, "SFO", "JFK", 30, "189", carrier="Delta"),
        _one_way("bd-out", *BD, "JFK", "SFO", 27, "320", "UA 1"),
        _one_way("bd-out-dear", *BD, "JFK", "SFO", 27, "420", "UA 3"),
        _one_way("bd-back", *BD, "SFO", "EWR", 30, "310", "UA 2"),
    ]
    assert [o.id for o in pick_flights(offers)] == ["bd-out", "bd-back"]
    assert source_counts(pick_flights(offers)) == (
        "Bright Data dataset gd_mhng7wen1rw0a3gvpf (Google Flights) x2")


def test_pick_flights_falls_back_to_next_tier_that_covers_the_trip() -> None:
    offers = [
        _one_way("bd-out", *BD, "JFK", "SFO", 27, "320", "UA 1"),       # no dataset return
        _one_way("un-out", *UN, "JFK", "SFO", 27, "330", "AA 9"),
        _one_way("un-back", *UN, "SFO", "JFK", 30, "300", "AA 8"),
        _one_way("ff-back", *FF, "SFO", "JFK", 30, "150", carrier="Delta"),
    ]
    assert [o.id for o in pick_flights(offers)] == ["un-out", "un-back"]


def test_pick_flights_mixes_tiers_per_leg_when_no_tier_is_complete() -> None:
    offers = [
        _one_way("bd-out", *BD, "JFK", "SFO", 27, "320", "UA 1"),
        _one_way("ff-back", *FF, "SFO", "JFK", 30, "150", carrier="Delta"),
    ]
    assert [o.id for o in pick_flights(offers)] == ["bd-out", "ff-back"]


def test_dedupe_flights_keeps_lowest_tier() -> None:
    offers = [
        _one_way("un", *UN, "JFK", "SFO", 27, "300", "UA 1"),
        _one_way("bd", *BD, "JFK", "SFO", 27, "320", "ua1"),
        _one_way("ff-a", *FF, "JFK", "SFO", 27, "250", carrier="Delta"),
        _one_way("ff-b", *FF, "JFK", "SFO", 27, "260", carrier="Delta"),
        _one_way("ff-c", *FF, "JFK", "SFO", 27, "270", carrier=None),
    ]
    assert sorted(o.id for o in dedupe_flights(offers)) == ["bd", "ff-a", "ff-c"]
