from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from conferge.core import brightdata, settings
from conferge.core.brightdata import BrightDataClient, BrightDataError


def test_from_env_reads_dotenv(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env = tmp_path / ".env"
    env.write_text("BRIGHTDATA_API_KEY=k\nBRIGHTDATA_SERP_ZONE=serp_z\n", encoding="utf-8")
    for name in ("BRIGHTDATA_API_KEY", "BRIGHTDATA_SERP_ZONE", "BRIGHTDATA_UNLOCKER_ZONE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(settings, "ENV_PATH", env)
    client = BrightDataClient.from_env()
    assert client.not_ready("serp") is None
    assert client.not_ready("web_unlocker") == "BRIGHTDATA_UNLOCKER_ZONE not configured"


@pytest.mark.asyncio
async def test_usage_counts_only_successful_responses() -> None:
    brightdata.reset_usage()
    ok = httpx.MockTransport(lambda r: httpx.Response(200, json=[
        {"a": 1}, {"a": 2}, {"error": "Crawler error: Unexpected Status 502 (no_peer)"}]))
    async with httpx.AsyncClient(transport=ok, base_url="https://api.brightdata.com") as http:
        out = await BrightDataClient("k", client=http).scrape_dataset("gd_x", [{"url": "u"}])
    assert out.status == "ready" and brightdata.usage()["datasets"] == 2
    bad = httpx.MockTransport(lambda r: httpx.Response(401))
    async with httpx.AsyncClient(transport=bad, base_url="https://api.brightdata.com") as http:
        with pytest.raises(BrightDataError, match="HTTP 401"):
            await BrightDataClient("k", client=http, retries=0, unlocker_zone="z").unlock("https://x.test/")
    assert brightdata.usage() == {"datasets": 2, "web_unlocker": 0, "serp": 0, "total": 2}
    brightdata.reset_usage()
