"""Refresh via Bright Data: MockTransport stands in for api.brightdata.com (no network)."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from conferge.api.app import create_app
from conferge.api.providers import Providers
from conferge.integration import travel_cache
from conferge.integration.assemble import assemble
from conferge.integration.live_refresh import make_client, refresh
from conferge.integration.sources import fixture_slices

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = (ROOT / "flights" / "data" / "google_flights_unlocker_sample.html").read_text(encoding="utf-8")
NOW = datetime(2026, 10, 24, 21, 30, tzinfo=timezone.utc)


def _demo():
    return assemble(fixture_slices(), travel_cache.load()).demo


def _client(handler):
    http = httpx.AsyncClient(base_url="https://api.brightdata.test",
                             transport=httpx.MockTransport(handler))
    client = make_client(http)
    client._api_key, client.unlocker_zone, client.serp_zone = "k", "web_unlocker1", "serp_api1"
    return client


def test_refresh_success_two_requests_live_flights_and_linkedin(tmp_path: Path) -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        calls.append(body["zone"])
        if body["zone"] == "web_unlocker1":
            return httpx.Response(200, text=SAMPLE)
        return httpx.Response(200, json={"organic": [
            {"link": "https://www.linkedin.com/in/jane-doe"}, {"link": "https://example.org"}]})

    demo = _demo()
    assert demo.domains["flights"].source_mode == "cached"
    result = asyncio.run(refresh(demo, ("Jane Doe", "Acme"), client=_client(handler),
                                 now=lambda: NOW, probe_dir=tmp_path))
    assert result["ok"] and result["requests"] == 2 and sorted(calls) == ["serp_api1", "web_unlocker1"]
    assert result["records"] == 3  # 2 itineraries + 1 LinkedIn profile
    assert result["lines"][0] == "Flights: cheapest round trip 413 USD cached at 11:18 → unchanged"
    assert result["lines"][1] == "LinkedIn: Jane Doe → https://www.linkedin.com/in/jane-doe"
    assert demo.domains["flights"].source_mode == "live" and demo.domains["flights"].collected_at == NOW
    assert all(e.source_mode == "live" for o in demo.flights for e in o.evidence)
    assert demo.flights[0].collected_at == NOW


def test_refresh_failure_red_reason_and_cache_kept(tmp_path: Path) -> None:
    demo = _demo()
    before_flights, before_domain = list(demo.flights), demo.domains["flights"]
    result = asyncio.run(refresh(demo, ("Jane Doe", "Acme"), now=lambda: NOW, probe_dir=tmp_path,
                                 client=_client(lambda r: httpx.Response(403, text="denied"))))
    assert not result["ok"] and result["lines"] == [] and result["records"] == 0
    assert result["errors"][0].startswith("Flights via Web Unlocker failed: BrightDataError")
    assert result["errors"][0].endswith("cached flights kept")
    assert demo.flights == before_flights and demo.domains["flights"] is before_domain


def test_endpoint_without_key_reports_and_changes_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("BRIGHTDATA_API_KEY", "BRIGHTDATA_UNLOCKER_ZONE", "BRIGHTDATA_SERP_ZONE"):
        monkeypatch.setenv(name, "")  # never the developer's .env key in a test
    demo = _demo()
    client = TestClient(create_app(data=demo, found=Providers(), graph_probe=False))
    before = client.get("/api/v1/flights").json()
    body = client.post("/api/v1/pipeline/refresh").json()
    assert body["refresh"]["ok"] is False and body["refresh"]["requests"] == 0  # nothing sent
    assert body["refresh"]["errors"] == ["BRIGHTDATA_API_KEY missing: nothing sent, cache kept"]
    after = client.get("/api/v1/flights").json()
    assert after["items"] == before["items"] and after["data_source"] == "cached"
    js = client.get("/static/app.js").text
    assert 'api("/pipeline/refresh", { method: "POST" }' in js and "refresh-error" in js
    assert 'id="btn-bd-refresh"' in client.get("/").text


def test_cached_profile_is_confirmed_and_the_raw_serp_is_kept(tmp_path: Path) -> None:
    serp = {"organic": [{"link": "https://fr.linkedin.com/in/RyanAHecht/", "title": "Ryan Hecht - GitHub",
                         "description": "Product at GitHub", "rank": 1}]}

    def handler(request: httpx.Request) -> httpx.Response:
        if json.loads(request.content)["zone"] == "web_unlocker1":
            return httpx.Response(200, text=SAMPLE)
        return httpx.Response(200, json=serp)

    result = asyncio.run(refresh(_demo(), ("Ryan Hecht", "GitHub"), client=_client(handler),
                                 now=lambda: NOW, probe_dir=tmp_path))
    assert "LinkedIn: 1 profile confirmed (cached)" in result["lines"]
    saved = json.loads(next(tmp_path.glob("refresh_serp_*.json")).read_text())
    assert saved["organic"][0] == {"link": "https://fr.linkedin.com/in/RyanAHecht/",
                                   "title": "Ryan Hecht - GitHub",
                                   "description": "Product at GitHub", "rank": 1}
    assert saved["query"] == 'site:linkedin.com/in "Ryan Hecht" GitHub'


def test_slow_unlocker_is_amber_cache_kept(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from conferge.integration import live_refresh

    monkeypatch.setattr(live_refresh, "UNLOCKER_TIMEOUT", 0.05)

    async def handler(request: httpx.Request) -> httpx.Response:
        if json.loads(request.content)["zone"] == "web_unlocker1":
            await asyncio.sleep(0.5)
            return httpx.Response(200, text=SAMPLE)
        return httpx.Response(200, json={"organic": []})

    demo = _demo()
    before = list(demo.flights)
    result = asyncio.run(refresh(demo, ("Jane Doe", "Acme"), client=_client(handler),
                                 now=lambda: NOW, probe_dir=tmp_path))
    assert result["slow"] and result["slow"][0].startswith("Bright Data slow, cache kept")
    assert result["errors"] == [] and result["ok"] is False and demo.flights == before
    assert "no profile in SERP (0 organic results)" in result["lines"][-1]


def test_key_without_zones_uses_default_zones_and_counts_sent_requests(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from conferge.integration import live_refresh

    monkeypatch.setenv("BRIGHTDATA_API_KEY", "k")
    monkeypatch.setenv("BRIGHTDATA_UNLOCKER_ZONE", "")
    monkeypatch.setenv("BRIGHTDATA_SERP_ZONE", "")
    zones: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        zones.append(json.loads(request.content)["zone"])
        return httpx.Response(200, text=SAMPLE) if zones[-1] == "web_unlocker1" \
            else httpx.Response(200, json={"organic": []})

    real = live_refresh.make_client
    monkeypatch.setattr(live_refresh, "make_client", lambda http=None: real(httpx.AsyncClient(
        base_url="https://api.brightdata.test", transport=httpx.MockTransport(handler))))
    result = asyncio.run(live_refresh.refresh(_demo(), ("Jane Doe", "Acme"), now=lambda: NOW,
                                              probe_dir=tmp_path))
    assert sorted(zones) == ["serp_api1", "web_unlocker1"] and result["requests"] == 2
    assert result["notes"] == ["default zones: web_unlocker1, serp_api1"]


def test_pipeline_requests_per_product_and_live_counter_apart_from_cache(
        monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BRIGHTDATA_API_KEY", "")
    client = TestClient(create_app(data=_demo(), found=Providers(), graph_probe=False))
    req = client.get("/api/v1/pipeline").json()["requests"]
    products = {p["product"]: p for p in req["at_collection_time"]}
    assert products["Booking"]["requests"] >= 1 and products["Booking"]["records"] == 15
    assert products["Google Flights"]["requests"] == 1 and products["Google Flights"]["records"] == 34
    from conferge.core.cost import snapshot

    assert req["since_start"] == snapshot()["by_api"]  # this process's calls, nothing cached
    assert "at collection time" in req["note"]
    bd = client.get("/api/v1/brightdata").json()
    assert bd["live"]["key_missing"] is True and bd["live"]["label"] == "key missing"
    assert bd["live"]["requests"] == snapshot()["requests"]  # live only, cache never added
    assert bd["cache_summary"]["records"] >= 72
    assert bd["cache_summary"]["requests_at_collection_time"] >= 1
    js = client.get("/static/app.js").text
    assert "Bright Data live: " in js and "Served from cache: " in js and "(key missing)" in js
