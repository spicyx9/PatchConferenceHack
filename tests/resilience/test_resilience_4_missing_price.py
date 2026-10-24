"""(4) Stay or flight without a price: amount null, never 0, never an estimate.

The contract names the status: ``Lodging.price_status`` ``unknown`` (docs/CONTRACTS.md:33,
"unknown charges remain unknown") or ``unavailable`` when the room itself is unavailable;
``FlightOffer.price_status`` has no ``unavailable`` value, a missing fare is ``unknown``
(conferge/core/schemas.py). See docs/ops/RESILIENCE_FINDINGS.md.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from fastapi.testclient import TestClient

from conferge.api.app import create_app
from conferge.api.data import load_fixture as load_api_fixture
from conferge.api.providers import Providers
from conferge.flights.normalize import RawOffer, RawSegment, RawSlice, build_offer
from conferge.lodging import fixture_query, load_fixture
from conferge.lodging.normalize import normalize

PRICE_KEY = re.compile(r"price|total|amount|rate|fee|tax|cost|charge", re.I)
UNPRICED = {"unknown", "unavailable"}
NOW = datetime(2026, 10, 24, 18, 0, tzinfo=timezone.utc)


def _strip_prices(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _strip_prices(v) for k, v in value.items() if not PRICE_KEY.search(k)}
    if isinstance(value, list):
        return [_strip_prices(v) for v in value]
    return value


def _unpriced_stays() -> list[Any]:
    records = load_fixture(explicit_opt_in=True).items
    q = fixture_query(explicit_opt_in=True)
    stays = []
    for record in records:
        bare = record.model_copy(update={"payload": _strip_prices(record.payload)})
        stay = normalize(bare, q, warnings=[], now=NOW)
        if stay is not None:
            stays.append(stay)
    return stays


def _unpriced_flight() -> Any:
    seg = RawSegment(origin="JFK", destination="SFO", departure="2026-10-27T08:00:00-04:00",
                     arrival="2026-10-27T11:30:00-07:00", marketing_carrier="B6")
    raw = RawOffer(provider="resilience", slices=[RawSlice(segments=[seg])], trip_type="one_way",
                   price=None, currency="USD")
    return build_offer(raw, NOW)


def test_missing_price_stays_null_never_zero_or_estimated() -> None:
    stays = _unpriced_stays()
    assert len(stays) >= 10  # booking, google_hotels and airbnb adapters all ran
    for stay in stays:
        assert stay.total_price is None and stay.nightly_avg is None, stay.id
        assert stay.base_total is None and stay.taxes is None and stay.fees_total is None
        assert stay.price_status in UNPRICED, (stay.id, stay.price_status)
    flight = _unpriced_flight()
    assert flight.total_price is None and flight.price_status == "unknown"
    assert "price_missing" in flight.warnings

    data = load_api_fixture()
    data.stays, data.flights = stays[:3], [flight]
    client = TestClient(create_app(data=data, found=Providers(), graph_probe=False))
    for item in client.get("/api/v1/stays").json()["items"]:
        assert item["total_price"] is None and item["nightly_avg"] is None
        assert item["price_status"] in UNPRICED
    offer = client.get("/api/v1/flights").json()["items"][0]
    assert offer["total_price"] is None and offer["price_status"] == "unknown"
    budget = client.get("/api/v1/travel").json()["budget"]
    assert budget["flights_usd"] is None and budget["lodging_usd"] is None
    assert budget["remaining_usd"] is None  # nothing estimated, nothing defaulted to 0
    for leg in client.get("/api/v1/travel").json()["itinerary"]:
        assert leg["price_status"] in UNPRICED
