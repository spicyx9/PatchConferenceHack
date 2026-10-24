"""Bright Data requests vs records, list-price estimate on dataset rows only (audit gap 2)."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from conferge.api.app import create_app
from conferge.api.providers import Providers
from conferge.core import brightdata, cost
from conferge.integration import brightdata_usage


@pytest.fixture(autouse=True)
def _clean_calls():
    brightdata.reset_usage()
    yield
    brightdata.reset_usage()


def test_list_price_constant_and_label() -> None:
    assert cost.DATASET_USD_PER_1000_RECORDS == Decimal("1.5")
    assert cost.COST_LABEL == "list price estimate, not billed"
    assert cost.dataset_cost(1000) == "1.5000"


def test_snapshot_separates_requests_and_records() -> None:
    calls = [{"api": "datasets", "rows": 0, "status": "running"},  # 202: a request, no rows yet
             {"api": "datasets", "rows": 15, "status": "ready"},
             {"api": "web_unlocker", "rows": 1, "status": "ready"},
             {"api": "serp", "rows": 1, "status": "ready"}]
    snap = cost.snapshot(calls)
    assert snap["requests"] == 4 and snap["records"] == 17
    assert snap["by_api"]["datasets"] == {"requests": 2, "records": 15}
    assert snap["by_api"]["unlocker"] == {"requests": 1, "records": 1}
    assert snap["usd"] == "0.0225"  # 15 dataset records only; Unlocker and SERP not priced


def _cache(tmp: Path) -> tuple[Path, Path]:
    cache, probes = tmp / "cache", tmp / "probes"
    cache.mkdir()
    probes.mkdir()
    stay = {"provenance": {"provider": "brightdata", "api": "dataset", "site": "booking",
                           "snapshot_id": "sd_a", "collected_at": "2026-10-24T18:41:14+00:00"}}
    page = "https://www.google.com/travel/flights?q=x"
    flight = {"provenance": {"provider": "brightdata", "api": "unlocker", "site": "google_flights",
                             "snapshot_id": None, "source_url": page,
                             "collected_at": "2026-10-24T18:18:14+00:00"}}
    (cache / "stays.json").write_text(json.dumps({"records": [stay] * 3, "runs": [
        {"provider": "google_hotels", "api": "dataset", "records": 0, "status": "failed",
         "collected_at": "2026-10-24T18:34:23+00:00"}]}))
    (cache / "flights.json").write_text(json.dumps({"records": [flight] * 34}))
    (cache / "linkedin_public.json").write_text(json.dumps({"profiles": [
        {"snapshot_id": "sd_l", "collected_at": "2026-10-24T19:14:00Z"},
        {"snapshot_id": "sd_l", "collected_at": "2026-10-24T19:16:00Z"},
        {"snapshot_id": None, "collected_at": "2026-10-24T20:07:00Z"}]}))
    (probes / "serp_linkedin.md").write_text(
        "- run at: 2026-10-24T20:43:12+00:00 (1 s)\n- targets: 17 announced speakers\n"
        "- URLs found: **5/17**; not found: 11\n")
    return cache, probes


def test_products_from_records(tmp_path: Path) -> None:
    cache, probes = _cache(tmp_path)
    by = {(p["product"], p["api"]): p for p in brightdata_usage.cached_products(cache, probes)}
    flights = by[("Google Flights", "unlocker")]
    assert (flights["requests"], flights["records"], flights["list_price_usd"]) == (1, 34, None)
    booking = by[("Booking", "dataset")]
    assert (booking["requests"], booking["records"], booking["list_price_usd"]) == (1, 3, "0.0045")
    assert booking["collected_first"] == "2026-10-24T18:41:14+00:00"
    assert by[("Google Hotels", "dataset")]["requests"] == 1  # recorded run, 0 records
    li = by[("LinkedIn", "dataset")]
    assert (li["requests"], li["records"]) == (2, 3)  # one snapshot + one synchronous scrape
    assert (li["collected_first"], li["collected_last"]) == ("2026-10-24T19:14:00Z", "2026-10-24T20:07:00Z")
    serp = by[("LinkedIn URL search", "serp")]
    assert (serp["requests"], serp["records"], serp["list_price_usd"]) == (17, 5, None)
    total = brightdata_usage.summary(cache, probes)
    assert total["requests"] == 1 + 1 + 1 + 2 + 17 and total["records"] == 34 + 3 + 3 + 5
    assert total["list_price_usd"] == "0.0090"  # 6 dataset records; never the 34 Unlocker rows


def test_brightdata_endpoint_never_uses_report_finish_time(monkeypatch) -> None:
    """Gap 1: the cached collected_at comes from records, not a pipeline row's finished_at."""
    from conferge.api.data import load_fixture

    data = load_fixture()
    data.pipeline = [{"source": "linkedin", "provider": "brightdata:linkedin", "kind": "brightdata",
                      "brightdata_api": "dataset", "records": 9, "cached": True, "status": "ok",
                      "collected_at": "2026-10-24T20:35:00+00:00"}]  # demo start time
    body = TestClient(create_app(data=data, found=Providers(), graph_probe=False)).get(
        "/api/v1/brightdata").json()
    stamps = [t for pair in body["cached"]["collected_at"].values() for t in pair]
    assert "2026-10-24T20:35:00+00:00" not in stamps
    assert body["cost_label"] == "list price estimate, not billed"
    assert {"requests", "records", "products"} <= set(body)


def test_cost_endpoint_reads_recorded_calls() -> None:
    client = TestClient(create_app(found=Providers(), graph_probe=False))
    assert client.get("/api/v1/cost").json()["requests"] == 0
    brightdata.record_call("web_unlocker", rows=34, status="ready")
    brightdata.record_call("datasets", rows=9, status="ready", snapshot_id="s_1")
    body = client.get("/api/v1/cost").json()
    assert body["requests"] == 2 and body["records"] == 43
    assert body["usd"] == "0.0135" and body["estimate"] is True
