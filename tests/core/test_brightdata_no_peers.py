"""Dataset no_peers / cooldown: 15, 30, 60 s, never a new billed POST after an ambiguous
timeout, a re-read of the same snapshot only, then degraded with ``brightdata_no_peers``.
No network: an in-process httpx transport answers; delays are recorded."""

from __future__ import annotations

import asyncio
from datetime import date

import httpx
import pytest

from conferge.core.brightdata import NO_PEERS, BrightDataClient, BrightDataError, has_no_peers

NO_PEER_ROW = {"error": "Crawler error: Unexpected Status 502 (no_peer)", "error_code": "no_peers",
               "input": {"search_term": "hotels"}}


def _client(answer):
    sleeps: list[float] = []
    calls: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        result = answer(len(calls), request)
        if isinstance(result, Exception):
            raise result
        return result

    async def sleep(seconds: float) -> None:
        sleeps.append(seconds)

    client = BrightDataClient("k", sleep=sleep, rand=lambda lo, hi: hi, client=httpx.AsyncClient(
        base_url="https://api.brightdata.test", transport=httpx.MockTransport(handler)))
    return client, sleeps, calls


def test_detection_covers_json_error_fields_records_and_raw_text() -> None:
    assert has_no_peers({"error": "zone in cooldown"}) and has_no_peers([NO_PEER_ROW])
    assert has_no_peers({"error_code": "no_peers"}) and has_no_peers("no_peers: try later")
    assert not has_no_peers([{"name": "Hotel"}]) and not has_no_peers({"status": "running"})


def test_scrape_answered_no_peers_is_sent_again_15_30_then_ok() -> None:
    client, sleeps, calls = _client(lambda n, r: httpx.Response(
        200, json=[NO_PEER_ROW] if n < 3 else [{"name": "Hotel"}]))
    out = asyncio.run(client.scrape_dataset("gd_x", [{"url": "https://e.org"}]))
    assert out.data == [{"name": "Hotel"}] and out.warnings == []
    assert sleeps == [15.0, 30.0] and len(calls) == 3


def test_scrape_no_peers_three_retries_then_warning() -> None:
    client, sleeps, calls = _client(lambda n, r: httpx.Response(200, json=[NO_PEER_ROW]))
    out = asyncio.run(client.scrape_dataset("gd_x", [{"url": "https://e.org"}]))
    assert sleeps == [15.0, 30.0, 60.0] and len(calls) == 4  # first + 3 retries
    assert out.warnings == [NO_PEERS]


def test_scrape_timeout_is_ambiguous_never_a_new_post() -> None:
    client, sleeps, calls = _client(lambda n, r: httpx.ReadTimeout("slow"))
    with pytest.raises(BrightDataError, match="timeout"):
        asyncio.run(client.scrape_dataset("gd_x", [{"url": "https://e.org"}]))
    assert calls == [("POST", "/datasets/v3/scrape")] and sleeps == []


def test_snapshot_no_peers_is_a_reread_of_the_same_snapshot_only() -> None:
    client, sleeps, calls = _client(lambda n, r: httpx.Response(
        200, json=[NO_PEER_ROW] if n < 4 else [{"name": "Hotel"}]))
    out = asyncio.run(client.snapshot_results("sd_same"))
    assert out.data == [{"name": "Hotel"}] and sleeps == [15.0, 30.0, 60.0]
    assert calls == [("GET", "/datasets/v3/snapshot/sd_same")] * 4  # no POST, same snapshot


def test_trigger_no_peers_answer_retried_timeout_not_resent() -> None:
    client, sleeps, calls = _client(lambda n, r: httpx.Response(
        200, json={"error": "no_peers"} if n == 1 else {"snapshot_id": "sd_1"}))
    assert asyncio.run(client.trigger_dataset("gd_x", [{"url": "https://e.org"}])) == "sd_1"
    assert sleeps == [15.0] and len(calls) == 2
    client, sleeps, calls = _client(lambda n, r: httpx.Response(200, json={"error": "no_peers"}))
    with pytest.raises(BrightDataError, match=NO_PEERS):
        asyncio.run(client.trigger_dataset("gd_x", [{"url": "https://e.org"}]))
    assert sleeps == [15.0, 30.0, 60.0]
    client, sleeps, calls = _client(lambda n, r: httpx.ReadTimeout("slow"))
    with pytest.raises(BrightDataError, match="timeout"):
        asyncio.run(client.trigger_dataset("gd_x", [{"url": "https://e.org"}]))
    assert len(calls) == 1


def test_http_error_with_no_peers_body_15_30_60_then_named_error() -> None:
    client, sleeps, calls = _client(lambda n, r: httpx.Response(502, text='{"error":"no_peers"}'))
    with pytest.raises(BrightDataError, match=f"HTTP 502 {NO_PEERS}"):
        asyncio.run(client.snapshot_progress("sd_x"))
    assert sleeps == [15.0, 30.0, 60.0] and len(calls) == 4


def test_google_hotels_source_is_degraded_with_brightdata_no_peers_in_the_panel() -> None:
    from conferge.integration.pipeline_view import row
    from conferge.lodging.google_hotels import GoogleHotelsSource
    from conferge.lodging.models import LodgingQuery

    client, sleeps, _ = _client(lambda n, r: httpx.Response(200, json=[NO_PEER_ROW]))
    q = LodgingQuery(check_in=date(2026, 10, 27), check_out=date(2026, 10, 30), adults=2,
                     verify_top=0)
    result = asyncio.run(GoogleHotelsSource(client=client).search(q))
    rep = result.run_report
    assert result.items == [] and rep.status == "degraded" and NO_PEERS in rep.warnings
    assert sleeps == [15.0, 30.0, 60.0]
    assert row("stays", rep)["reason"] == NO_PEERS
