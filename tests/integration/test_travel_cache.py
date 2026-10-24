from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from conferge.api.app import create_app
from conferge.api.providers import Providers
from conferge.integration import travel_cache
from conferge.integration.assemble import assemble
from conferge.integration.sources import fixture_slices


def test_committed_cache_holds_normalized_bright_data_records_only() -> None:
    import json

    for domain, name in travel_cache.FILES.items():
        text = (travel_cache.CACHE_DIR / name).read_text(encoding="utf-8")
        assert "<html" not in text.lower() and "linkedin" not in text.lower()
        doc = json.loads(text)
        assert doc["kind"] == "conferge.travel_cache" and doc["records"]
        for rec in doc["records"]:
            p = rec["provenance"]
            assert p["provider"] == "brightdata" and p["api"] in {"dataset", "unlocker"}
            assert p["id"] and p["source_url"] and p["collected_at"] and p["price_status"]
            if p["api"] == "dataset":
                assert p["snapshot_id"], rec


def test_cache_is_served_labelled_cached_with_provenance_and_pipeline_rows(no_network: None) -> None:
    travel = travel_cache.load()
    assert travel and travel["stays"].source_mode == "cached"
    demo = assemble(fixture_slices(), travel).demo
    client = TestClient(create_app(data=demo, found=Providers(), graph_probe=False))

    stays = client.get("/api/v1/stays").json()
    assert stays["data_source"] == "cached" and stays["items"]
    assert all(i["source"]["provider"] == "brightdata" for i in stays["items"])
    assert all(i["price_status"] == "quoted_total" and i["total_price"] for i in stays["items"])
    assert all(e["source_mode"] == "cached" for i in stays["items"] for e in i["evidence"])

    flights = client.get("/api/v1/flights").json()
    assert flights["data_source"] == "cached" and flights["items"]
    offer = flights["items"][0]
    assert offer["trip_type"] == "round_trip" and offer["price_status"] == "quoted_total"
    assert offer["price_label"] == "round trip total" and offer["source"]["api"] == "unlocker"

    rows = client.get("/api/v1/pipeline").json()["rows"]
    cached = [r for r in rows if r.get("cached")]
    assert {r["brightdata_api"] for r in cached} == {"dataset", "unlocker"}
    assert sum(r["records"] for r in cached) == 55  # 21 stays + 34 itineraries
    bd = client.get("/api/v1/brightdata").json()["cached"]
    assert bd["total"] == 55 and bd["datasets"] == 21 and bd["web_unlocker"] == 34
    assert all(v.startswith("2026-10-24") for v in bd["collected_at"].values())


def test_no_cache_keeps_the_labelled_fixture(tmp_path: Path, no_network: None) -> None:
    assert travel_cache.available(tmp_path) is False and travel_cache.load(tmp_path) is None
    demo = assemble(fixture_slices(), None).demo
    body = TestClient(create_app(data=demo, found=Providers(), graph_probe=False)) \
        .get("/api/v1/stays").json()
    assert body["data_source"] == "fixture"
