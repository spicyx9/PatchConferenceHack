"""fast-flights mapping with a fake module shaped like fast-flights 3.1.0 (commit 7c105db).

Object shapes mirror fast_flights.model (Flights, SingleFlight, Airport,
SimpleDatetime) as observed live on 2026-10-24; values here are fictional.
"""

import sys
import types
from datetime import date, datetime, timezone
from types import SimpleNamespace as NS

from conferge.flights.fastflights_provider import FastFlightsProvider
from conferge.flights.normalize import RawOffer, RawSegment, RawSlice, build_offer
from conferge.flights.proposals import compare_dates
from conferge.flights.service import FlightSearchQuery

NOW = datetime(2026, 10, 24, 18, 0, tzinfo=timezone.utc)


def _flight(o, d, day, dep, arr, minutes):
    return NS(from_airport=NS(code=o, name=o), to_airport=NS(code=d, name=d),
              departure=NS(date=day, time=dep), arrival=NS(date=day, time=arr),
              duration=minutes, plane_type="Test 320")


def _fake_module(monkeypatch, fail_return=False):
    module = types.ModuleType("fast_flights")

    class Query:
        def __init__(self, legs):
            self.legs = legs

        def url(self):
            return "https://www.google.com/travel/flights/search?tfs=FAKE"

    module.FlightQuery = lambda **kw: kw
    module.Passengers = lambda **kw: kw
    module.create_query = lambda **kw: Query(kw["flights"])

    def get_flights(query, **_):
        leg = query.legs[0]
        if leg["from_airport"] == "JFK":
            return [NS(type="ZZ", price=372, airlines=["Test Air"],
                       flights=[_flight("JFK", "SFO", (2026, 10, 27), (7, 32), (11, 12), 400)]),
                    NS(type="multi", price=None, airlines=["A", "B"],
                       flights=[_flight("JFK", "SFO", (2026, 10, 27), (9, 0), (12, 31), 391)])]
        if fail_return:
            raise RuntimeError("blocked")
        return [NS(type="ZZ", price=301, airlines=["Test Air"],
                   flights=[_flight("SFO", "JFK", (2026, 10, 30), (13, 0), (21, 35), 335)])]

    module.get_flights = get_flights
    monkeypatch.setitem(sys.modules, "fast_flights", module)
    monkeypatch.delenv("BRIGHTDATA_API_KEY", raising=False)


async def test_two_one_way_searches_mapped_honestly(monkeypatch):
    _fake_module(monkeypatch)
    offers, report = await FastFlightsProvider(clock=lambda: NOW).search_round_trip(
        "JFK", "SFO", date(2026, 10, 27), date(2026, 10, 30))
    assert report.status == "ok" and all(o.trip_type == "one_way" for o in offers)
    priced = {o.total_price for o in offers}
    assert priced == {"372", "301", None}
    out = next(o for o in offers if o.total_price == "372")
    seg = out.slices[0].segments[0]
    assert seg.departure_at.isoformat() == "2026-10-27T07:32:00-04:00"
    assert seg.arrival_at.isoformat() == "2026-10-27T11:12:00-07:00"
    assert seg.marketing_carrier == "ZZ" and seg.flight_number is None
    assert out.booking_url_type == "google_flights_search"
    multi = next(o for o in offers if o.total_price is None)
    assert multi.slices[0].segments[0].marketing_carrier is None
    assert multi.price_status == "unknown"
    assert any("round_trip_as_two_one_way" in w for w in report.warnings)


async def test_one_direction_failure_is_degraded(monkeypatch):
    _fake_module(monkeypatch, fail_return=True)
    offers, report = await FastFlightsProvider(clock=lambda: NOW).search_round_trip(
        "JFK", "SFO", date(2026, 10, 27), date(2026, 10, 30))
    assert offers and report.status == "degraded"
    assert any(e.startswith("return RuntimeError") for e in report.errors)


def _one_way(o, d, day, price):
    raw = RawOffer(provider="x", trip_type="one_way", price=price, currency="USD",
                   slices=[RawSlice([RawSegment(o, d, f"{day}T08:00", f"{day}T11:30", "ZZ")])])
    return build_offer(raw, NOW)


def test_proposals_sum_one_way_directions_without_mixing():
    q = FlightSearchQuery(origin_city="New York", destination_city="San Francisco",
                          departure_date=date(2026, 10, 27), return_date=date(2026, 10, 30))
    base = [_one_way("JFK", "SFO", "2026-10-27", "372"), _one_way("SFO", "JFK", "2026-10-30",
                                                                  "301")]
    alt = [_one_way("JFK", "SFO", "2026-10-26", "190"), _one_way("SFO", "JFK", "2026-10-30",
                                                                 "301")]
    proposal = compare_dates("depart_day_before", q, base, alt, source_mode="live")
    assert proposal.base_price == "673" and proposal.alternative_price == "491"
    assert proposal.saving == "182" and len(proposal.base_offer_ids) == 2
    assert any("sum_of_two_one_way_fares" in w for w in proposal.warnings)
