"""Cold judge 2026-10-24: /pipeline said data_source=live with no key and only cached rows."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from conferge.api.app import _pipeline_mode, create_app
from conferge.api.providers import Providers
from conferge.core.schemas import RunReport
from conferge.integration import travel_cache
from conferge.integration.assemble import assemble
from conferge.integration.pipeline_view import row
from conferge.integration.sources import fixture_slices

NOW = datetime(2026, 10, 24, 22, 0, tzinfo=timezone.utc)


def _live_row() -> dict:
    rep = RunReport(provider="brightdata_unlocker_google_flights", started_at=NOW, finished_at=NOW,
                    status="ok", termination="exhausted", source_mode="live", fetched_count=34,
                    unique_count=34, warnings=["via Web Unlocker 1x"])
    return row("flights", rep)


def test_cached_rows_are_labelled_cached_never_live() -> None:
    demo = assemble(fixture_slices(), travel_cache.load()).demo
    client = TestClient(create_app(data=demo, found=Providers(), graph_probe=False))
    body = client.get("/api/v1/pipeline").json()
    assert body["data_source"] == "cached"
    assert all(r["cached"] for r in body["rows"] if r["kind"] != "fallback" and r.get("records"))


def test_live_rows_from_this_process_are_live_or_mixed() -> None:
    cached = [r for r in assemble(fixture_slices(), travel_cache.load()).demo.pipeline
              if r["kind"] != "fallback"]
    assert _pipeline_mode(cached) == "cached"
    assert _pipeline_mode([*cached, _live_row()]) == "mixed"  # after a real Refresh
    assert _pipeline_mode([_live_row()]) == "live"
    assert _pipeline_mode([]) == "fixture"
