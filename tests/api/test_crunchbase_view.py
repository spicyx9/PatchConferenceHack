"""/api/v1/people shows Crunchbase funding from the public cache (read-only), offline."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from conferge.api.app import create_app
from conferge.api.providers import Providers
from conferge.core.schemas import Company
from conferge.people import crunchbase as cb

NOW = datetime(2026, 10, 24, 12, tzinfo=timezone.utc)
URL = "https://www.crunchbase.com/organization/agentworks"


def _items(client: TestClient) -> list[dict]:
    return client.get("/api/v1/people", params={"limit": 50}).json()["items"]


def test_people_card_shows_cached_funding(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    funding = {"total_funding_usd": "12500000", "last_round_type": "series_a",
               "last_round_date": "2025-05-01", "investors": ["Fund A"],
               "employee_range": "11-50", "founded": "2021"}
    path = cb.write_public_cache([cb.public_entry(
        Company(id="co-fx-agentworks", name="AgentWorks"), URL, funding,
        snapshot_id="sd_view", collected_at=NOW)], tmp_path / "crunchbase_public.json")
    monkeypatch.setattr(cb, "PUBLIC_CACHE", path)
    client = TestClient(create_app(found=Providers(), graph_probe=False))
    items = _items(client)
    with_funding = [i for i in items if i["company"] and i["company"]["id"] == "co-fx-agentworks"]
    assert with_funding, "fixture person at co-fx-agentworks expected in /people"
    company = with_funding[0]["company"]
    assert company["funding"]["total_funding_usd"] == "12500000"
    assert company["last_round"] == {"type": "series_a", "label": "Series A",
                                     "date": "2025-05-01"}
    evidence = company["evidence"][-1]
    assert evidence == {"provider": "brightdata:crunchbase", "source_mode": "cached",
                        "source_url": URL, "collected_at": NOW.isoformat(), "raw_ref": "sd_view"}
    others = [i["company"] for i in items
              if i["company"] and i["company"]["id"] != "co-fx-agentworks"]
    assert all("funding" not in c for c in others)


def test_people_card_without_cache(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cb, "PUBLIC_CACHE", tmp_path / "absent.json")
    client = TestClient(create_app(found=Providers(), graph_probe=False))
    assert all("funding" not in i["company"] for i in _items(client) if i["company"])
