from datetime import date, datetime, timedelta, timezone

import pytest

from conferge.core.schemas import RunReport
from conferge.flights.normalize import RawOffer, RawSegment, RawSlice, build_offer
from conferge.flights.proposals import compare_dates, propose_alternatives
from conferge.flights import BrightDataFlightsSource, load_fixture
from conferge.core.brightdata import BrightDataClient
from conferge.core.contracts import Source
from conferge.flights.service import FlightSearchQuery, FlightService, load_fixture_offers, run

NOW = datetime(2026, 10, 24, 18, 0, tzinfo=timezone.utc)
QUERY = {"origin_city": "New York", "destination_city": "San Francisco",
         "departure_date": "2026-10-27", "return_date": "2026-10-30"}


def _report(name, status="ok", n=1):
    return RunReport(
        provider=name, started_at=NOW, finished_at=NOW, status=status,
        termination="exhausted" if status == "ok" else "error", source_mode="live",
        fetched_count=n, unique_count=n, errors=[] if status == "ok" else [f"{name} down"],
    )


def _offer(provider, origin, dest, dep_day, ret_day, price, number="ZZ101"):
    raw = RawOffer(provider=provider, trip_type="round_trip", price=price, currency="USD",
                   slices=[
                       RawSlice([RawSegment(origin, dest, f"{dep_day}T08:00", f"{dep_day}T11:30",
                                            "ZZ", None, number)]),
                       RawSlice([RawSegment(dest, origin, f"{ret_day}T13:00", f"{ret_day}T21:35",
                                            "ZZ", None, "ZZ102")]),
                   ])
    return build_offer(raw, NOW)


class FakeProvider:
    def __init__(self, name, offers_by_pair=None, fail=False, price=None):
        self.name, self.offers_by_pair, self.fail, self.price = name, offers_by_pair, fail, price
        self.calls = []

    async def search_round_trip(self, origin, destination, departure, return_date, *,
                                adults=1, cabin="economy"):
        self.calls.append((origin, destination, departure, return_date))
        if self.fail:
            return [], _report(self.name, "failed", 0)
        price = self.price(origin, destination, departure, return_date) if self.price else "400"
        return [_offer(self.name, origin, destination, departure, return_date, price,
                       number=f"ZZ{len(origin)}{origin}")], _report(self.name)


class BoomProvider:
    async def search_round_trip(self, *args, **kwargs):
        raise RuntimeError("bug")


async def test_fan_out_over_multiple_airports_and_router_fallback():
    primary, secondary = FakeProvider("bd", fail=True), FakeProvider("ff")
    service = FlightService([("bd", primary), ("ff", secondary)])
    env = await run(QUERY, service=service)
    pairs = {(o, d) for o, d, *_ in primary.calls}
    assert pairs == {(o, d) for o in ("JFK", "LGA", "EWR") for d in ("SFO", "OAK")}
    assert len(secondary.calls) == 6
    assert env.source_mode == "live" and env.status == "degraded" and len(env.items) == 6
    assert any(r.status == "failed" for r in env.reports)


async def test_provider_exception_is_reported_and_all_failed_without_fixture():
    service = FlightService([("bd", BoomProvider())])
    env = await service.search(FlightSearchQuery.model_validate(QUERY))
    assert env.status == "failed" and env.items == [] and env.source_mode == "live"
    assert any("RuntimeError" in e for e in env.errors)


async def test_fixture_only_when_explicit_and_labelled():
    service = FlightService([("bd", FakeProvider("bd", fail=True))])
    q = FlightSearchQuery.model_validate(QUERY)
    env = await service.search(q, allow_fixture=True)
    assert env.source_mode == "fixture" and env.status == "degraded"
    assert len(env.items) == 4  # alternatives J-1 / J+1 are filtered by date
    assert all(e.source_mode == "fixture" for o in env.items for e in o.evidence)
    assert all(o.price_status == "unknown" for o in env.items)
    assert any("FIXTURE" in e for e in env.errors)
    with pytest.raises(RuntimeError):
        load_fixture_offers()


async def test_cache_reuses_results_within_ttl():
    clock = {"now": NOW}
    provider = FakeProvider("bd")
    service = FlightService([("bd", provider)], clock=lambda: clock["now"])
    q = FlightSearchQuery.model_validate({**QUERY, "origin_city": "JFK",
                                          "destination_city": "SFO"})
    await service.search(q)
    await service.search(q)
    assert len(provider.calls) == 1
    clock["now"] = NOW + timedelta(minutes=21)
    await service.search(q)
    assert len(provider.calls) == 2


def test_compare_dates_threshold_and_event_reason():
    q = FlightSearchQuery.model_validate(QUERY)
    base = [_offer("x", "JFK", "SFO", "2026-10-27", "2026-10-30", "412")]
    cheap = [_offer("x", "JFK", "SFO", "2026-10-26", "2026-10-30", "301")]
    small = [_offer("x", "JFK", "SFO", "2026-10-26", "2026-10-30", "350")]
    proposal = compare_dates("depart_day_before", q, base, cheap, source_mode="live")
    assert proposal.saving == "111" and proposal.departure_date == date(2026, 10, 26)
    assert compare_dates("depart_day_before", q, base, small, source_mode="live") is None
    by_event = compare_dates("depart_day_before", q, base, small, source_mode="live",
                             event_day_before=True)
    assert by_event is not None and "event" in by_event.reason
    assert compare_dates("return_day_after", q, base, [], source_mode="live") is None


async def test_propose_alternatives_searches_j_minus_1_and_j_plus_1():
    def price(origin, destination, departure, return_date):
        if departure == date(2026, 10, 26):
            return "250"
        if return_date == date(2026, 10, 31):
            return "390"
        return "400"

    provider = FakeProvider("bd", price=price)
    service = FlightService([("bd", provider)])
    q = FlightSearchQuery.model_validate({**QUERY, "origin_city": "JFK",
                                          "destination_city": "SFO"})
    proposals = await propose_alternatives(service, q)
    assert [p.kind for p in proposals] == ["depart_day_before"]
    assert proposals[0].saving == "150" and proposals[0].source_mode == "live"
    assert {c[2] for c in provider.calls} == {date(2026, 10, 27), date(2026, 10, 26)}


def test_package_exports_source_contract_and_labelled_fixture():
    assert isinstance(BrightDataFlightsSource(BrightDataClient(None)), Source)
    env = load_fixture()
    assert env.source_mode == "fixture" and len(env.items) == 6
    assert all("test_data" in w for o in env.items for w in o.warnings[:1])
