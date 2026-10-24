"""source_of: provider/API provenance read from real-shaped evidence, plus API exposure."""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from fastapi.testclient import TestClient

from conferge.api.app import create_app
from conferge.api.data import load_fixture
from conferge.api.provenance import source_of
from conferge.api.providers import Providers
from conferge.core.schemas import FlightOffer, Lodging, SourceEvidence

NOW = datetime(2026, 10, 24, 17, 0, tzinfo=timezone.utc)
KEYS = {"provider", "api", "id", "site", "snapshot_id", "tier", "label", "collected_at"}


def ev(provider: str, raw_ref: str | None = None, mode: str = "live") -> list[SourceEvidence]:
    return [SourceEvidence(provider=provider, source_mode=mode, collected_at=NOW, raw_ref=raw_ref,
                           source_url="https://www.booking.com/hotel/us/x.html",
                           source_record_id="x")]


def test_booking_dataset_with_snapshot_and_detail_evidence() -> None:
    evidence = [*ev("booking", "s_m9abc123"),
                SourceEvidence(provider="booking", source_mode="live", collected_at=NOW,
                               raw_ref="gd_mdy9ld3p1e0oqlj9g4", source_record_id="x")]
    src = source_of(evidence)
    assert set(src) == KEYS
    assert src == {"provider": "brightdata", "api": "dataset", "id": "gd_m4bf7a917zfezv9d5",
                   "site": "booking", "snapshot_id": "s_m9abc123", "tier": 0,
                   "label": "Bright Data dataset gd_m4bf7a917zfezv9d5 (Booking)",
                   "collected_at": NOW.isoformat()}


def test_google_hotels_dataset_without_snapshot() -> None:
    src = source_of(ev("google_hotels"))
    assert (src["provider"], src["api"], src["id"], src["site"], src["snapshot_id"], src["tier"]) \
        == ("brightdata", "dataset", "gd_mg3gjfmg12tc2n5d4d", "google_hotels", None, 0)
    assert src["label"] == "Bright Data dataset gd_mg3gjfmg12tc2n5d4d (Google Hotels)"


def test_airbnb_brightdata_vs_pyairbnb_by_raw_ref() -> None:
    bd = source_of(ev("airbnb", "s_airbnb42"))
    assert (bd["provider"], bd["api"], bd["id"], bd["snapshot_id"], bd["tier"]) == (
        "brightdata", "dataset", "gd_ld7ll037kqy322v05", "s_airbnb42", 0)
    py = source_of(ev("airbnb", None))
    assert py == {"provider": "pyairbnb", "api": "fallback", "id": None, "site": "airbnb",
                  "snapshot_id": None, "tier": 2, "label": "Fallback pyairbnb",
                  "collected_at": py["collected_at"]}


def test_lodging_unlocker_zone_and_site() -> None:
    src = source_of(ev("unlocker", "unlocker:web_unlocker1:hilton"))
    assert src == {"provider": "brightdata", "api": "unlocker", "id": "web_unlocker1",
                   "site": "hilton", "snapshot_id": None, "tier": 1,
                   "label": "Bright Data Web Unlocker web_unlocker1 (Hilton)",
                   "collected_at": src["collected_at"]}


def test_flight_providers() -> None:
    ds = source_of(ev("brightdata_google_flights", "s_flt1"))
    assert (ds["api"], ds["id"], ds["site"], ds["snapshot_id"], ds["tier"]) == (
        "dataset", "gd_mhng7wen1rw0a3gvpf", "google_flights", "s_flt1", 0)
    un = source_of(ev("brightdata_unlocker_google_flights",
                      "unlocker:web_unlocker1:google_flights"))
    assert (un["api"], un["id"], un["site"], un["tier"]) == (
        "unlocker", "web_unlocker1", "google_flights", 1)
    assert un["label"] == "Bright Data Web Unlocker web_unlocker1 (Google Flights)"
    ff = source_of(ev("fast_flights_google_flights"))
    assert (ff["provider"], ff["api"], ff["tier"], ff["label"]) == (
        "fast-flights", "fallback", 2, "Fallback fast-flights")
    serp = source_of(ev("serpapi_google_flights", "search-id-1"))
    assert (serp["provider"], serp["api"], serp["tier"]) == ("serpapi", "serp", 2)


def test_fixture_and_unknown() -> None:
    assert source_of(ev("fixture:w06"))["api"] == "fixture"
    fx = source_of(ev("booking", "s_1", mode="fixture"))
    assert (fx["provider"], fx["api"], fx["tier"], fx["label"]) == (
        "fixture", "fixture", 3, "Fixture")
    assert source_of([])["tier"] == 3
    assert source_of(ev("somewhere-else"))["provider"] == "unknown"


def test_api_exposes_source_on_stays_flights_and_travel() -> None:
    demo = load_fixture()
    stay = Lodging(id="booking:1", provider="booking", name="Hotel Zephyr",
                   total_price=Decimal("900.00"), currency="USD", price_status="quoted_total",
                   check_in=date(2026, 10, 27), check_out=date(2026, 10, 30), adults=2,
                   evidence=ev("booking", "s_snap"))
    offer = FlightOffer.model_validate({
        "id": "bd:1", "trip_type": "one_way", "collected_at": NOW, "total_price": "300",
        "currency": "USD", "price_status": "observed_live",
        "evidence": ev("brightdata_google_flights", "s_flt"),
        "slices": [{"segments": [{"origin_iata": "JFK", "destination_iata": "SFO",
                                  "departure_at": "2026-10-27T08:00:00-04:00",
                                  "flight_number": "B6 415", "marketing_carrier": "JetBlue"}]}],
    })
    demo.stays, demo.flights = [stay], [offer]
    client = TestClient(create_app(data=demo, found=Providers(), graph_probe=False))
    stays = client.get("/api/v1/stays").json()["items"]
    assert stays[0]["source"]["label"] == "Bright Data dataset gd_m4bf7a917zfezv9d5 (Booking)"
    flights = client.get("/api/v1/flights").json()["items"]
    assert flights[0]["source"]["id"] == "gd_mhng7wen1rw0a3gvpf"
    legs = client.get("/api/v1/travel").json()["itinerary"]
    assert {leg["kind"] for leg in legs} == {"flight", "stay"}
    assert all(set(leg["source"]) == KEYS for leg in legs)
    assert [leg["source"]["tier"] for leg in legs] == [0, 0]
