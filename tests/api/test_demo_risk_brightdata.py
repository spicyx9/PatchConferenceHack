"""Risk 1 of the wiring audit: /brightdata must not claim "live" without a Bright Data key."""

from __future__ import annotations

from fastapi.testclient import TestClient

from conferge.api.app import create_app
from conferge.api.providers import Providers


def _client() -> TestClient:
    return TestClient(create_app(found=Providers(), graph_probe=False))


def test_brightdata_without_key_is_unknown_not_live(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    for var in ("BRIGHTDATA_API_KEY", "BRIGHT_DATA_API_KEY", "BRIGHTDATA_API_TOKEN"):
        monkeypatch.delenv(var, raising=False)
    from conferge.core import brightdata as bd

    monkeypatch.setattr(bd.BrightDataClient, "not_ready", lambda self, api: "key missing")
    body = _client().get("/api/v1/brightdata").json()
    assert body["ready"] == {"datasets": False, "web_unlocker": False, "serp": False}
    assert body["data_source"] == "unknown"
    assert any("not configured" in w for w in body["warnings"])


def test_brightdata_with_a_ready_api_is_live(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from conferge.core import brightdata as bd

    monkeypatch.setattr(bd.BrightDataClient, "not_ready",
                        lambda self, api: None if api == "serp" else "zone missing")
    body = _client().get("/api/v1/brightdata").json()
    assert body["ready"]["serp"] is True and body["data_source"] == "live"


def test_demo_screen_does_not_feed_brightdata_into_the_global_badge() -> None:
    from pathlib import Path

    js = Path(__file__).resolve().parents[2] / "static" / "app.js"
    text = js.read_text(encoding="utf-8")
    assert 'api("/brightdata", null, "brightdata")' not in text
    assert 'api("/brightdata", null, null)' in text
