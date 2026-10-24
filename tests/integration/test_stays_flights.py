from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from fastapi.testclient import TestClient

from conferge.api.app import create_app
from conferge.api.providers import Providers
from conferge.core.schemas import FlightOffer, Lodging, SourceEvidence
from conferge.integration.assemble import assemble
from conferge.integration.sources import fixture_slices
from conferge.integration.stays_flights import LiveDomain, pick_flights

NOW = datetime(2026, 10, 24, 17, 21, tzinfo=timezone.utc)
LIVE = [SourceEvidence(provider="test-live", source_mode="live", collected_at=NOW)]


def _stay(sid: str, total: str) -> Lodging:
    return Lodging(id=sid, provider="airbnb", name=f"Stay {sid}", total_price=Decimal(total),
                   price_status="quoted_total", currency="USD", evidence=LIVE,
                   check_in=date(2026, 10, 27), check_out=date(2026, 10, 30), adults=1)


def _one_way(fid: str, origin: str, dest: str, day: int, price: str) -> FlightOffer:
    dep = datetime(2026, 10, day, 15, 0, tzinfo=timezone.utc)
    return FlightOffer.model_validate({
        "id": fid, "trip_type": "one_way", "collected_at": NOW, "evidence": LIVE,
        "total_price": price, "currency": "USD", "price_status": "observed_live",
        "slices": [{"segments": [{"origin_iata": origin, "destination_iata": dest,
                                  "departure_at": dep.isoformat()}]}],
    })


def _flights() -> list[FlightOffer]:
    return [
        _one_way("out-oak", "JFK", "OAK", 27, "297"),
        _one_way("out-sfo", "JFK", "SFO", 27, "372"),
        _one_way("back-sfo", "SFO", "JFK", 30, "382"),
        _one_way("back-sfo-cheap", "SFO", "EWR", 30, "334"),
    ]


def test_pick_flights_keeps_cheapest_sfo_outbound_and_return() -> None:
    assert [o.id for o in pick_flights(_flights())] == ["out-sfo", "back-sfo-cheap"]


def test_live_travel_replaces_fixture_with_labels(no_network: None) -> None:
    live = {
        "stays": LiveDomain("stays", [_stay("airbnb:1", "617.00")], "live", "degraded", NOW,
                            ["booking: failed"]),
        "flights": LiveDomain("flights", pick_flights(_flights()), "live", "ok", NOW),
    }
    demo = assemble(fixture_slices(), live).demo
    assert [s.id for s in demo.stays] == ["airbnb:1"]
    assert demo.domains["stays"].source_mode == "live"
    assert demo.domains["stays"].status == "degraded"
    assert demo.domains["flights"].collected_at == NOW
    client = TestClient(create_app(data=demo, found=Providers(), graph_probe=False))
    stays = client.get("/api/v1/stays").json()
    assert stays["data_source"] == "live"
    assert stays["items"][0]["total_price"] == "617.00"
    assert stays["items"][0]["price_status"] == "quoted_total"
    travel = client.get("/api/v1/travel").json()
    assert travel["budget"]["flights_usd"] == "706"
    assert [leg["date"] for leg in travel["itinerary"] if leg["kind"] == "flight"] == [
        "2026-10-27", "2026-10-30"]


def test_failed_or_empty_live_falls_back_to_labelled_fixture(no_network: None) -> None:
    live = {
        "stays": LiveDomain("stays", [], "live", "degraded", NOW),
        "flights": LiveDomain("flights", errors=["timeout: TimeoutError"]),
    }
    demo = assemble(fixture_slices(), live).demo
    for name in ("stays", "flights"):
        domain = demo.domains[name]
        assert domain.source_mode == "fixture"
        assert any("fixture fallback" in w for w in domain.warnings)
        assert getattr(demo, name)
        assert all(e.source_mode == "fixture" for x in getattr(demo, name) for e in x.evidence)
    assert any("TimeoutError" in w for w in demo.domains["flights"].warnings)
    client = TestClient(create_app(data=demo, found=Providers(), graph_probe=False))
    assert client.get("/api/v1/flights").json()["data_source"] == "fixture"
