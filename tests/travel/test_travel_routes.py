from datetime import datetime, timedelta, timezone

from conferge.travel.models import Place, Price, ProviderOutcome, RouteLeg, utcnow
from conferge.travel.places import EMBARCADERO, FORT_MASON, SFO, SJC
from conferge.travel.providers.base import RouteProvider, failed, report
from conferge.travel.routes import RoutePlanner, combine_prices


def leg(a: Place, b: Place, mode, minutes, price: Price, dep=None, provider="fake"):
    arr = dep + timedelta(minutes=minutes) if dep and minutes is not None else None
    return RouteLeg(
        from_place=a, to_place=b, mode=mode, departure_local=dep, arrival_local=arr,
        duration_minutes=minutes, duration_status="unknown" if minutes is None else "estimate",
        price=price, provider=provider, source_mode="live", collected_at=utcnow(),
    )


class Fake:
    def __init__(self, name, modes, minutes=None, price=None, fail=False):
        self.name, self.modes = name, frozenset(modes)
        self.minutes, self.price, self.fail = minutes, price or Price(), fail
        self.calls = []

    async def route(self, origin, destination, *, mode, depart_at=None):
        started = utcnow()
        self.calls.append((origin.id, destination.id, mode, depart_at))
        if self.fail:
            return failed(self.name, started, f"{self.name} down")
        return ProviderOutcome(
            legs=[leg(origin, destination, mode, self.minutes, self.price, depart_at, self.name)],
            run_report=report(self.name, started, status="ok", termination="exhausted",
                              fetched=1, pages=1),
        )


DEP = datetime(2026, 10, 28, 1, 0, tzinfo=timezone.utc)
USD = dict(currency="USD")


def test_fake_satisfies_protocol():
    assert isinstance(Fake("x", {"walk"}), RouteProvider)


def test_combine_prices_never_sums_unknown():
    assert combine_prices([Price(amount="11.80", status="exact", **USD), Price()]).status == "unknown"
    total = combine_prices([Price(amount="11.80", status="exact", **USD),
                            Price(amount="0", status="exact", **USD)])
    assert total.amount == "11.80" and total.status == "exact"
    est = combine_prices([Price(amount="1", status="exact", **USD),
                          Price(amount="2.5", status="estimate", **USD)])
    assert est.amount == "3.5" and est.status == "estimate"


async def test_airport_bart_then_walk_chains_times():
    bart = Fake("bart", {"bart"}, 31, Price(amount="11.80", status="exact", **USD))
    walk = Fake("osrm", {"walk"}, 54, Price(amount="0", status="exact", **USD))
    drive = Fake("osrm", {"drive"}, 29)
    planner = RoutePlanner(bart=bart, walk=walk, drive=drive)
    plan = await planner.plan(SFO, FORT_MASON, depart_at=DEP)
    rail = plan.options[0]
    assert [x.mode for x in rail.legs] == ["bart", "walk"]
    assert rail.legs[1].from_place.id == EMBARCADERO.id
    assert walk.calls[0][3] == DEP + timedelta(minutes=31)
    assert rail.total_duration_minutes == 85 and rail.complete
    assert rail.total_price.amount == "11.80"
    taxi = plan.options[1]
    assert taxi.total_price.status == "unknown" and not taxi.complete
    assert any("fare unknown" in w for w in taxi.warnings)
    assert plan.status == "ok" and plan.source_mode == "live"
    assert any("511" in e for e in plan.errors)


async def test_walk_falls_back_and_failure_is_degraded():
    bart = Fake("bart", {"bart"}, 31, Price(amount="11.80", status="exact", **USD))
    osrm = Fake("osrm", {"walk"}, fail=True)
    hav = Fake("haversine", {"walk"}, 60, Price(amount="0", status="exact", **USD))
    plan = await RoutePlanner(bart=bart, walk=osrm, walk_fallback=hav).plan(
        SFO, FORT_MASON, depart_at=DEP)
    assert plan.options[0].legs[1].provider == "haversine"
    assert plan.status == "degraded"
    assert "osrm down" in plan.errors


async def test_no_providers_fails_without_inventing():
    plan = await RoutePlanner().plan(SFO, FORT_MASON, depart_at=DEP)
    assert plan.options == [] and plan.status == "failed"


async def test_sjc_has_no_rail_option():
    bart = Fake("bart", {"bart"}, 31)
    plan = await RoutePlanner(bart=bart, drive=Fake("osrm", {"drive"}, 70)).plan(
        SJC, FORT_MASON)
    assert bart.calls == []
    assert [o.label for o in plan.options] == ["Taxi or rideshare (driving time)"]
    assert any("no BART station" in e for e in plan.errors)


async def test_rideshare_estimate_is_labelled_estimate():
    uber = Fake("uber", {"rideshare"}, None, Price(amount="45", status="estimate", **USD))
    plan = await RoutePlanner(drive=Fake("osrm", {"drive"}, 29), rideshare=uber).plan(
        SFO, FORT_MASON)
    opt = plan.options[0]
    assert opt.total_price.status == "estimate" and opt.total_price.amount == "45"


async def test_sequence_between_program_places():
    walk = Fake("osrm", {"walk"}, 12, Price(amount="0", status="exact", **USD))
    hotel = Place(id="hotel-x", name="Hotel X", kind="hotel", latitude=37.80, longitude=-122.42)
    plans = await RoutePlanner(walk=walk).plan_sequence([hotel, FORT_MASON, EMBARCADERO])
    assert len(plans) == 2 and all(p.options[0].label == "Walk" for p in plans)
