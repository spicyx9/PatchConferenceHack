"""Slow provider jobs remain observable without relaunching their collections."""
import asyncio
import time

from fastapi.testclient import TestClient

from conferge.api.app import create_app
from conferge.extras import travel_search

QUERY = {"kind": "stays", "mode": "live", "origin": "New York",
         "destination": "San Francisco", "depart": "2026-10-27",
         "return_date": "2026-10-30", "adults": 2}


def test_pending_collection_can_be_polled_and_identical_requests_share_it(monkeypatch):
    calls = []

    async def collect(query):
        calls.append(query)
        await asyncio.sleep(0.1)
        return {"query": query.model_dump(mode="json"), "status": "ok",
                "data_source": "live", "items": [{"id": "observed-stay"}], "count": 1}

    monkeypatch.setattr(travel_search, "search_live", collect)
    with TestClient(create_app(graph_probe=False)) as client:
        response = client.post("/api/v1/travel/search", json=QUERY)
        assert response.status_code == 202
        initial = response.json()
        assert initial["status"] == "running" and initial["items"] == []
        duplicate = client.post("/api/v1/travel/search", json=QUERY).json()
        assert duplicate["job_id"] == initial["job_id"]
        for _ in range(30):
            result = client.get("/api/v1/travel/search/" + initial["job_id"]).json()
            if result["status"] != "running":
                break
            time.sleep(0.02)
        assert result["status"] == "ok" and result["data_source"] == "live"
        assert result["items"] == [{"id": "observed-stay"}]
        assert len(calls) == 1


def test_failed_collection_is_not_replaced_by_old_cached_offers(monkeypatch):
    async def collect(query):
        return {"status": "failed", "data_source": "unknown", "items": [], "count": 0}

    monkeypatch.setattr(travel_search, "search_live", collect)
    with TestClient(create_app(graph_probe=False)) as client:
        initial = client.post("/api/v1/travel/search", json=QUERY).json()
        result = client.get("/api/v1/travel/search/" + initial["job_id"]).json()
        assert result["status"] == "failed" and result["items"] == []
        assert client.get("/api/v1/travel/search/missing").status_code == 404
