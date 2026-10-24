"""Bright Data audit (docs/audits/BRIGHTDATA_E2E_2026-10-24.md), gaps 1 to 4, proved on data/cache."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import Mock

from fastapi.testclient import TestClient

from conferge.api.app import create_app
from conferge.api.providers import Providers
from conferge.core.schemas import RunReport
from conferge.core.store import GraphStore
from conferge.graph.ingest import GraphIngestor
from conferge.integration import travel_cache
from conferge.integration.assemble import assemble
from conferge.integration.pipeline_view import row
from conferge.integration.sources import fixture_slices


def _demo(no_network: None):  # type: ignore[no-untyped-def]
    travel = travel_cache.load()
    assert travel
    return assemble(fixture_slices(), travel).demo


def _iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def test_gap1_cached_collected_at_comes_from_records_not_from_the_demo_start(no_network: None) -> None:
    demo = _demo(no_network)
    started = datetime.now(timezone.utc)
    # A LinkedIn RunReport of a demo start finishes "now": that must never become a collection time.
    linkedin = RunReport(provider="brightdata:linkedin", started_at=started, finished_at=started,
                         status="ok", termination="exhausted", source_mode="cached",
                         fetched_count=9, unique_count=9)
    demo.pipeline.append(row("linkedin", linkedin))
    client = TestClient(create_app(data=demo, found=Providers(), graph_probe=False))
    body = client.get("/api/v1/brightdata").json()
    stamps = body["cached"]["collected_at"]
    assert {"Booking", "Google Flights", "LinkedIn"} <= set(stamps)
    assert stamps["Booking"][1].startswith("2026-10-24T18:41")
    assert stamps["Google Flights"] == ["2026-10-24T18:18:14+00:00", "2026-10-24T18:18:14+00:00"]
    for first, last in stamps.values():
        assert _iso(first) <= _iso(last) < started
    for product in body["products"]:
        if product["collected_last"]:
            assert _iso(product["collected_last"]) < started, product


def test_gap2_requests_and_records_apart_and_no_usd_anywhere(no_network: None) -> None:
    demo = _demo(no_network)
    client = TestClient(create_app(data=demo, found=Providers(), graph_probe=False))
    body = client.get("/api/v1/brightdata").json()
    flights = next(p for p in body["products"] if p["product"] == "Google Flights")
    # 34 itineraries parsed from one Web Unlocker page: 34 records, 1 request, never "34 collected".
    assert (flights["api"], flights["requests"], flights["records"]) == ("unlocker", 1, 34)
    assert body["cost_usd"] is None and "not read from any Bright Data response" in body["cost_note"]
    assert set(body["usage"]) == {"returned", "requests", "unit"}
    pipeline = client.get("/api/v1/pipeline").json()
    assert pipeline["totals"]["cost_usd"] is None
    for payload in (body, pipeline, client.get("/api/v1/cost").json()):
        text = str(payload)
        for banned in ("estimated_cost", "list_price", "estimate_basis", "not billed", "$"):
            assert banned not in text, banned


def test_gap3_flight_shown_says_what_the_graph_stores(no_network: None) -> None:
    demo = _demo(no_network)
    assert demo.flights, "the cache serves at least one flight"
    # GraphStore.merge_node is the only way to FalkorDB: read its payloads back.
    store = Mock(spec=GraphStore)
    GraphIngestor(store, default_mode="fixture").ingest_flights(demo.flights)
    nodes = {c.args[1]: c.args[2] for c in store.merge_node.call_args_list if c.args[0] == "FlightOffer"}
    client = TestClient(create_app(data=demo, found=Providers(), graph_probe=False))
    # The kept itinerary is the one in the graph; cached alternatives are listed, not ingested.
    items = {i["id"]: i for i in client.get("/api/v1/flights").json()["items"] if i["kept"]}
    assert set(items) <= set(nodes) and items
    for fid, item in items.items():
        node = nodes[fid]
        for key in ("trip_type", "total_price", "price_status", "currency", "raw_price_text",
                    "return_slice_collected"):
            assert item.get(key) == node.get(key), (fid, key, item.get(key), node.get(key))
        if item["total_price"] is not None:
            # A total is shown only from the record itself: the same text the page carried.
            assert item["raw_price_text"] and item["total_price"] in item["raw_price_text"]
    budget = client.get("/api/v1/travel").json()["budget"]
    assert budget["flights_price_status"] == [f.price_status for f in demo.flights[:1]]


def test_gap4_every_travel_item_served_carries_its_mode_and_collection_time(no_network: None) -> None:
    demo = _demo(no_network)
    client = TestClient(create_app(data=demo, found=Providers(), graph_probe=False))
    for path in ("/api/v1/stays", "/api/v1/flights"):
        items = client.get(path).json()["items"]
        assert items, path
        for item in items:
            assert item["source"]["collected_at"], (path, item["id"])
            assert all(e["source_mode"] == "cached" for e in item["evidence"]), (path, item["id"])
