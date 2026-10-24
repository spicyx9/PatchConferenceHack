from datetime import timezone

import httpx
import pytest

from conferge.core.brightdata import BrightDataClient, BrightDataError


@pytest.mark.asyncio
async def test_dataset_discovery_sync_and_no_token_leak():
    calls = []

    def mock(req: httpx.Request) -> httpx.Response:
        calls.append(req)
        return httpx.Response(200, json=[{"url": "https://example.org/event"}])

    async with httpx.AsyncClient(
        base_url="https://api.brightdata.com", transport=httpx.MockTransport(mock)
    ) as client:
        bd = BrightDataClient("secret-should-never-log", client=client)
        res = await bd.scrape_dataset("dataset123", [{"q": "GitHub Universe"}],
                                      method="discover_by_input_filters", limit_per_input=5)
        assert res.status == "ready" and res.source_mode == "live"
        assert calls[0].url.params["discover_by"] == "input_filters"
        assert calls[0].url.params["limit_per_input"] == "5"


@pytest.mark.asyncio
async def test_async_trigger_and_snapshot():
    def mock(req: httpx.Request) -> httpx.Response:
        if req.url.path.endswith("/trigger"):
            return httpx.Response(200, json={"snapshot_id": "s123"})
        if "/progress/" in req.url.path:
            return httpx.Response(200, json={"status": "ready"})
        if "/snapshot/" in req.url.path:
            return httpx.Response(200, json=[{"url": "https://example.org"}])
        raise AssertionError(f"unexpected path {req.url.path}")

    async with httpx.AsyncClient(
        base_url="https://api.brightdata.com", transport=httpx.MockTransport(mock)
    ) as client:
        bd = BrightDataClient("api-key", client=client)
        snapshot_id = await bd.trigger_dataset("dataset", [{"url": "https://example.org"}])
        assert snapshot_id == "s123"
        assert (await bd.snapshot_progress(snapshot_id))["status"] == "ready"
        assert (await bd.snapshot_results(snapshot_id)).status == "ready"


@pytest.mark.asyncio
async def test_http_errors_are_sanitized():
    def mock(req: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"debug": "secret"})

    async with httpx.AsyncClient(
        base_url="https://api.brightdata.com", transport=httpx.MockTransport(mock)
    ) as client:
        bd = BrightDataClient("secret", client=client)
        with pytest.raises(BrightDataError) as err:
            await bd.scrape_dataset("dataset", [{"url": "https://example.org"}])
        assert "secret" not in str(err.value)
        assert "HTTP 403" in str(err.value)


def test_fixtures_opt_in_only(tmp_path):
    path = tmp_path / "flight.json"
    path.write_text('[{"price":"99"}]')
    with pytest.raises(BrightDataError):
        BrightDataClient.load_fixture(path)
    output = BrightDataClient.load_fixture(path, explicit_opt_in=True)
    assert output.source_mode == "fixture" and "FIXTURE" in output.warnings[0]


def test_collection_output_timestamp_aware():
    from conferge.core.brightdata import CollectionOutput
    assert CollectionOutput(status="ready", source_mode="live").collected_at.tzinfo == timezone.utc
