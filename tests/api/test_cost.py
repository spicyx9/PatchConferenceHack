"""GET /api/v1/cost: live Bright Data call counter, USD estimate (core/cost.py)."""

from __future__ import annotations

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from conferge.api.app import create_app
from conferge.api.providers import Providers
from conferge.core import brightdata, cost


@pytest.fixture(autouse=True)
def _clean_calls():
    brightdata.reset_usage()
    yield
    brightdata.reset_usage()


def test_constant_is_the_documented_estimate() -> None:
    assert cost.BRIGHT_DATA_USD_PER_CALL == Decimal("0.0015")
    assert "real price not verified" in cost.snapshot([])["basis"]


def test_snapshot_counts_calls_per_api() -> None:
    calls = [{"api": "datasets"}, {"api": "datasets"}, {"api": "web_unlocker"}, {"api": "serp"}]
    snap = cost.snapshot(calls)
    assert snap["calls"] == 4
    assert snap["by_api"] == {"datasets": 2, "unlocker": 1, "serp": 1}
    assert snap["usd"] == "0.0060" and snap["estimate"] is True


def test_snapshot_empty_is_zero_not_missing() -> None:
    snap = cost.snapshot()
    assert snap["calls"] == 0 and snap["usd"] == "0.0000"
    assert snap["by_api"] == {"datasets": 0, "unlocker": 0, "serp": 0}


def test_cost_endpoint_reads_recorded_calls() -> None:
    client = TestClient(create_app(found=Providers(), graph_probe=False))
    body = client.get("/api/v1/cost").json()
    assert body["calls"] == 0 and body["data_source"] == "unknown"
    brightdata.record_call("web_unlocker", rows=1, status="ready")
    brightdata.record_call("datasets", rows=9, status="ready", snapshot_id="s_1")
    body = client.get("/api/v1/cost").json()
    assert body["calls"] == 2
    assert body["by_api"] == {"datasets": 1, "unlocker": 1, "serp": 0}
    assert body["usd"] == "0.0030" and body["estimate"] is True
    assert any("estimate" in w for w in body["warnings"])
