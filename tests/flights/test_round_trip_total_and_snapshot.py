from __future__ import annotations

import asyncio
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from conferge.api.app import create_app
from conferge.api.data import load_fixture as load_api_fixture
from conferge.api.providers import Providers
from conferge.core.schemas import FlightOffer, SourceEvidence
from conferge.flights.round_trip_total import as_stored, display, round_trip_total, trip_price
from conferge.flights.snapshot_provider import GoogleFlightsSnapshotProvider, latest_snapshot
from conferge.integration.stays_flights import pick_flights

NOW = datetime(2026, 10, 24, 19, 0, tzinfo=timezone.utc)


def _offer(fid: str, provider: str, origin: str, dest: str, day: int, *, price: str | None = None,
           raw: str | None = None, raw_ref: str | None = None) -> FlightOffer:
    dep = datetime(2026, 10, day, 15, 0, tzinfo=timezone.utc)
    return FlightOffer.model_validate({
        "id": fid, "trip_type": "one_way", "collected_at": NOW,
        "total_price": price, "currency": "USD" if price else None,
        "price_status": "observed_live" if price else "unknown", "raw_price_text": raw,
        "slices": [{"segments": [{"origin_iata": origin, "destination_iata": dest,
                                  "departure_at": dep.isoformat(), "flight_number": f"{fid}1",
                                  "marketing_carrier": "B6"}]}],
        "evidence": [SourceEvidence(provider=provider, source_mode="live", collected_at=NOW,
                                    raw_ref=raw_ref)],
    })


UNLOCKER = "brightdata_unlocker_google_flights"
ZONE = "unlocker:web_unlocker1:google_flights"


def test_round_trip_total_is_stored_as_shown_and_never_split() -> None:
    legacy = _offer("u1", UNLOCKER, "JFK", "SFO", 27, raw="716 USD round trip total", raw_ref=ZONE)
    assert round_trip_total(legacy) == ("716", "USD")
    rt = as_stored(legacy)
    assert (rt.trip_type, rt.total_price, rt.currency, rt.price_status, rt.return_slice_collected) \
        == ("round_trip", "716", "USD", "quoted_total", False)
    assert rt.raw_price_text == "716 USD round trip total" and rt.id == legacy.id
    assert len(rt.slices) == 1 and str(trip_price(rt)) == "716"
    assert as_stored(rt) == rt  # idempotent
    assert display(rt) == {"price_label": "round trip total"}  # a label, nothing overridden
    assert display(_offer("f1", "fast_flights_google_flights", "JFK", "SFO", 27, price="333")) == {}


def test_unlocker_round_trip_beats_cheaper_fast_flights_fallback() -> None:
    offers = [
        _offer("f1", "fast_flights_google_flights", "JFK", "SFO", 27, price="333"),
        _offer("f2", "fast_flights_google_flights", "SFO", "JFK", 30, price="345"),
        as_stored(_offer("u1", UNLOCKER, "JFK", "SFO", 27, raw="716 USD round trip total",
                         raw_ref=ZONE)),
        as_stored(_offer("u2", UNLOCKER, "EWR", "SFO", 27, raw="413 USD round trip total",
                         raw_ref=ZONE)),
    ]
    assert [o.id for o in pick_flights(offers)] == ["u2"]
    data = load_api_fixture()
    data.flights = pick_flights(offers)
    client = TestClient(create_app(data=data, found=Providers(), graph_probe=False))
    item = client.get("/api/v1/flights").json()["items"][0]
    assert (item["trip_type"], item["price_status"], item["total_price"]) == (
        "round_trip", "quoted_total", "413")
    assert item["source"]["provider"] == "brightdata" and item["source"]["api"] == "unlocker"
    travel = client.get("/api/v1/travel").json()
    assert travel["budget"]["flights_usd"] == "413"
    leg = next(x for x in travel["itinerary"] if x["kind"] == "flight")
    assert leg["price_label"] == "round trip total" and leg["total_price"] == "413"


def _snapshot(tmp: Path, collected: datetime, rows: list) -> None:
    tmp.mkdir(parents=True, exist_ok=True)
    (tmp / f"google_flights_{collected:%Y-%m-%d}.json").write_text(json.dumps({
        "dataset_id": "gd_mhng7wen1rw0a3gvpf", "status": "ready", "rows": rows,
        "snapshots": [{"kind": "discover", "snapshot_id": "sd_test"}],
        "collected_at": collected.isoformat()}), encoding="utf-8")


def test_snapshot_older_than_24h_is_refused(tmp_path: Path) -> None:
    _snapshot(tmp_path, NOW - timedelta(hours=25), [{"legs": []}])
    snap, why = latest_snapshot(tmp_path, now=NOW)
    assert snap is None and "> 24 h" in why
    offers, rep = asyncio.run(GoogleFlightsSnapshotProvider(tmp_path, clock=lambda: NOW)
                              .search_round_trip("JFK", "SFO", date(2026, 10, 27),
                                                 date(2026, 10, 30)))
    assert offers == [] and rep.status == "failed" and "24 h" in rep.errors[0]


def test_missing_snapshot_is_a_failed_report(tmp_path: Path) -> None:
    offers, rep = asyncio.run(GoogleFlightsSnapshotProvider(tmp_path / "none", clock=lambda: NOW)
                              .search_round_trip("JFK", "SFO", date(2026, 10, 27),
                                                 date(2026, 10, 30)))
    assert offers == [] and rep.status == "failed" and rep.source_mode == "cached"
