"""Travel research must never substitute another trip or relabel fixtures."""
from copy import deepcopy
from urllib.parse import parse_qs, urlparse

from fastapi import FastAPI
from fastapi.testclient import TestClient

from conferge.extras.travel_search import TravelSearch, fallback_url, router, search_cached
from conferge.integration import travel_cache


def query(**changes):
    values = {"kind": "flights", "origin": "New York", "destination": "San Francisco",
              "depart": "2026-10-27", "return_date": "2026-10-30"}
    return TravelSearch.model_validate({**values, **changes})


def test_matching_flights_preserve_collected_prices_and_sources():
    result = search_cached(query())
    assert result["count"] > 1
    assert result["data_source"] == "cached"
    assert result["query"]["adults"] == 1
    assert result["collected_at"]
    for item in result["items"]:
        assert item["source"]["provider"] != "fixture"
        assert all(e["source_mode"] == "cached" for e in item["evidence"])
        assert item["slices"][0]["segments"][0]["departure_at"].startswith("2026-10-27")
        assert item["source"]["label"]
    # Observed round-trip text stays a round-trip total, not a fabricated one-way fare.
    assert any(item.get("raw_price_text") for item in result["items"])


def test_unsupported_queries_do_not_return_demo_cache():
    for changed in ({"origin": "Paris"}, {"depart": "2026-10-26"},
                    {"return_date": "2026-10-31"}, {"adults": 2}, {"cabin": "business"},
                    {"destination": "London"}):
        result = search_cached(query(**changed))
        assert result["items"] == []
        assert result["data_source"] == "unknown"
        assert result["supported"] is False
        assert result["fallback_url"]


def test_stay_occupancy_dates_proximity_and_budget_are_exact():
    result = search_cached(query(kind="stays", adults=2, radius_km=1, budget=550))
    assert result["count"]
    for item in result["items"]:
        assert item["adults"] == 2 and item["rooms"] == 1
        assert item["check_in"] == "2026-10-27"
        assert item["distance_to_venue_m"] <= 1000
        assert float(item["total_price"]) <= 550
        assert item["currency"] == "USD"
    for changed in ({"adults": 1}, {"adults": 3}, {"rooms": 2},
                    {"depart": "2026-10-26"}, {"destination": "Paris"}):
        assert not search_cached(query(kind="stays", **changed))["items"]


def test_search_endpoint_does_not_mutate_conference_selection():
    app = FastAPI()
    app.state.selection = {"flight": None, "stay": None}
    app.include_router(router)
    before = deepcopy(app.state.selection)
    response = TestClient(app).post("/api/v1/travel/search", json=query().model_dump(mode="json"))
    assert response.status_code == 200 and response.json()["count"]
    assert app.state.selection == before
    invalid = query().model_dump(mode="json")
    invalid["return_date"] = "2026-10-26"
    assert TestClient(app).post("/api/v1/travel/search", json=invalid).status_code == 422


def test_no_cache_is_not_replaced_with_a_fixture(tmp_path):
    result = search_cached(query(), tmp_path)
    assert result["count"] == 0 and result["data_source"] == "unknown"


def test_fixture_in_cache_cannot_be_reported_as_collected(tmp_path):
    import json
    document = json.loads((travel_cache.CACHE_DIR / "flights.json").read_text())
    for row in document["records"]:
        for ev in row["record"]["evidence"]:
            ev["source_mode"] = "fixture"
    (tmp_path / "flights.json").write_text(json.dumps(document))
    assert search_cached(query(), tmp_path)["items"] == []


def test_fallback_encodes_exact_travelers_and_dates():
    q = query(origin="Paris", adults=3, cabin="business")
    text = parse_qs(urlparse(fallback_url(q)).query)["q"][0]
    assert all(word in text for word in ["Paris", "2026-10-27", "2026-10-30", "3 adults", "business"])
    url = parse_qs(urlparse(fallback_url(query(kind="stays", adults=2, rooms=2))).query)
    assert url["group_adults"] == ["2"] and url["no_rooms"] == ["2"]


def test_one_way_never_receives_round_trip_cache_or_return_search_criteria():
    q = query(trip_type="one_way", return_date="2026-10-26")
    result = search_cached(q)
    assert result["items"] == [] and result["supported"] is False
    text = parse_qs(urlparse(result["fallback_url"]).query)["q"][0]
    assert "one way" in text and "returning" not in text
    assert "2026-10-26" not in text


async def test_live_flights_use_requested_route_and_preserve_live_provenance(monkeypatch):
    from datetime import datetime, timezone
    from conferge.core.schemas import DataEnvelope, FlightOffer
    from conferge.extras import travel_search
    cached = search_cached(query())["items"][0]
    record = travel_search._records("flights", travel_cache.CACHE_DIR)[0]
    record = record.model_copy(update={"evidence": [ev.model_copy(update={"source_mode": "live"})
                                                  for ev in record.evidence]})
    calls = []

    async def collect(q):
        calls.append(q)
        return DataEnvelope[FlightOffer](items=[record], source_mode="live", status="ok",
                                         collected_at=datetime.now(timezone.utc))

    monkeypatch.setattr(travel_search, "_run_live_flights", collect)
    result = await travel_search.search_live(query(mode="live"))
    assert calls[0].origin == "New York" and calls[0].adults == 1
    assert result["count"] == 1 and result["data_source"] == "live"
    assert result["items"][0]["source"]["provider"] == cached["source"]["provider"]
    # A provider accidentally returning the demo route for Paris must not leak it into results.
    mismatch = await travel_search.search_live(query(mode="live", origin="Paris"))
    assert mismatch["count"] == 0 and mismatch["data_source"] == "unknown"


async def test_live_stays_missing_credentials_never_substitutes_cache(monkeypatch):
    from conferge.extras import travel_search
    monkeypatch.setattr(travel_search, "env_value", lambda name: None)

    async def forbidden(q):
        raise AssertionError("An unconfigured provider must not be contacted")

    monkeypatch.setattr(travel_search, "_run_live_stays", forbidden)
    result = await travel_search.search_live(query(kind="stays", adults=2, mode="live"))
    assert not result["items"] and result["status"] == "failed"
    assert any("not configured" in text for text in result["warnings"])


async def test_live_hotel_collection_is_query_bound_and_keeps_actual_price(monkeypatch):
    from datetime import datetime, timezone
    from conferge.core.schemas import DataEnvelope, Lodging
    from conferge.extras import travel_search
    stay = travel_search._records("stays", travel_cache.CACHE_DIR)[0]
    stay = stay.model_copy(update={"evidence": [e.model_copy(update={"source_mode": "live"})
                                              for e in stay.evidence]})
    calls = []
    monkeypatch.setattr(travel_search, "env_value", lambda name: "configured")

    async def collect(q):
        calls.append(q)
        return DataEnvelope[Lodging](items=[stay], source_mode="live", status="ok",
                                     collected_at=datetime.now(timezone.utc))

    monkeypatch.setattr(travel_search, "_run_live_stays", collect)
    result = await travel_search.search_live(query(kind="stays", adults=2, mode="live"))
    assert result["count"] == 1 and result["items"][0]["total_price"] == str(stay.total_price)
    assert calls[0].adults == 2 and calls[0].rooms == 1
    changed = await travel_search.search_live(query(kind="stays", adults=1, mode="live"))
    assert changed["count"] == 0


async def test_live_timeout_and_provider_errors_are_explicit_and_redacted(monkeypatch):
    import asyncio
    from conferge.extras import travel_search

    async def fail(q):
        raise RuntimeError("secret-api-key-and-internal-url")

    monkeypatch.setattr(travel_search, "_run_live_flights", fail)
    result = await travel_search.search_live(query(mode="live"))
    assert result["status"] == "failed" and not result["items"]
    assert "secret-api-key" not in str(result)

    async def timeout(q):
        raise asyncio.TimeoutError()

    monkeypatch.setattr(travel_search, "_run_live_flights", timeout)
    result = await travel_search.search_live(query(mode="live"))
    assert any("50 seconds" in text for text in result["warnings"])
    assert result["data_source"] == "unknown"


async def test_live_flight_adapter_wires_structured_query_without_demo_providers(monkeypatch):
    from conferge.extras import travel_search
    from conferge.flights import service
    captured = {}
    monkeypatch.setattr(travel_search, "env_value", lambda name: None)

    async def run(data, **kwargs):
        captured.update(data=data, kwargs=kwargs)
        return "result"

    monkeypatch.setattr(service, "run", run)
    assert await travel_search._run_live_flights(query(origin="Paris", mode="live")) == "result"
    assert captured["data"]["origin_city"] == "Paris"
    assert captured["kwargs"]["allow_fixture"] is False
    assert [name for name, _ in captured["kwargs"]["service"].providers] == ["fastflights"]


async def test_live_hotel_adapter_passes_dates_rooms_occupancy_and_radius(monkeypatch):
    from conferge.extras import travel_search
    from conferge import lodging
    captured = []

    async def run(data):
        captured.append(data)
        return "result"

    monkeypatch.setattr(lodging, "run", run)
    q = query(kind="stays", mode="live", adults=3, rooms=2, radius_km=2)
    assert await travel_search._run_live_stays(q) == "result"
    actual = captured[0]
    assert actual.adults == 3 and actual.rooms == 2 and actual.radius_km == 2
    assert actual.check_in == q.depart and actual.check_out == q.return_date


async def test_brightdata_live_adapter_only_runs_for_its_exact_query_scope(monkeypatch):
    from conferge.extras import travel_search
    from conferge.flights import service
    captured = []
    credentials = {"BRIGHTDATA_API_KEY": "test-only-key", "BRIGHTDATA_UNLOCKER_ZONE": "test-zone"}
    monkeypatch.setattr(travel_search, "env_value", credentials.get)

    async def run(data, **kwargs):
        captured.append([name for name, _ in kwargs["service"].providers])

    monkeypatch.setattr(service, "run", run)
    await travel_search._run_live_flights(query(mode="live", destination="SFO"))
    assert captured[-1][0] == "brightdata_unlocker"
    await travel_search._run_live_flights(query(mode="live"))
    assert captured[-1][0] == "brightdata_unlocker"
    for changed in ({"origin": "Paris"}, {"depart": "2026-10-26"},
                    {"return_date": "2026-10-31"}, {"adults": 2}, {"cabin": "business"},
                    {"destination": "OAK"}):
        await travel_search._run_live_flights(query(mode="live", **changed))
        assert "brightdata_unlocker" not in captured[-1]
    credentials.pop("BRIGHTDATA_API_KEY")
    await travel_search._run_live_flights(query(mode="live", destination="SFO"))
    assert "brightdata_unlocker" not in captured[-1]
