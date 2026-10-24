"""w03: githubuniverse.com GETs go through Bright Data Web Unlocker when ready, else direct."""

from __future__ import annotations

import json

import httpx
import pytest

from conferge.core.brightdata import BrightDataClient, BrightDataError
from conferge.events.official.rainfocus import RainFocusClient

PAGE = {"data": {"responseCode": "0"}}


class FakeBD(BrightDataClient):
    def __init__(self, zone: str | None, fail: bool = False) -> None:
        super().__init__("k", unlocker_zone=zone, client=httpx.AsyncClient())
        self.fail, self.urls = fail, []

    async def unlock(self, url: str) -> str:
        self.urls.append(url)
        if self.fail:
            raise BrightDataError("Bright Data /request: HTTP 401")
        return json.dumps(PAGE)


def _direct(calls: list[str]) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, json=PAGE)
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_portal_get_uses_web_unlocker_when_ready() -> None:
    calls: list[str] = []
    bd = FakeBD("unlocker_zone")
    client = RainFocusClient(_direct(calls), brightdata=bd)
    data = await client._json("GET", "https://reg.githubuniverse.com/flow/loadPage", params={"a": "1"})
    assert data == PAGE and calls == []
    assert bd.urls == ["https://reg.githubuniverse.com/flow/loadPage?a=1"]
    assert client.transport == {"brightdata:web_unlocker": 1, "direct": 0}


@pytest.mark.asyncio
@pytest.mark.parametrize("zone, fail, note", [
    (None, False, "BRIGHTDATA_UNLOCKER_ZONE not configured"),
    ("unlocker_zone", True, "Web Unlocker failed"),
])
async def test_portal_get_falls_back_to_direct(zone, fail, note) -> None:  # type: ignore[no-untyped-def]
    calls: list[str] = []
    client = RainFocusClient(_direct(calls), brightdata=FakeBD(zone, fail))
    assert await client._json("GET", "https://reg.githubuniverse.com/flow/loadPage") == PAGE
    assert len(calls) == 1 and client.transport["direct"] == 1
    assert any(note in n for n in client.drain_notes())


@pytest.mark.asyncio
async def test_rainfocus_api_post_stays_direct() -> None:
    calls: list[str] = []
    bd = FakeBD("unlocker_zone")
    client = RainFocusClient(_direct(calls), brightdata=bd)
    await client._json("POST", "https://events.rainfocus.com/api/search", data={"type": "session"})
    assert bd.urls == [] and calls == ["https://events.rainfocus.com/api/search"]
