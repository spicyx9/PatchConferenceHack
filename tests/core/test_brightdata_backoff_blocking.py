"""Backoff, Retry-After, cooldown and Web Unlocker block detection. No network: an in-process
httpx transport answers; delays are recorded instead of slept."""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone
from email.utils import format_datetime
from pathlib import Path

import httpx
import pytest

from conferge.core.brightdata import (
    BrightDataClient,
    BrightDataError,
    block_reason,
    retry_after_seconds,
)

ROOT = Path(__file__).resolve().parents[1]


def _client(answers: list, *, retries: int = 2, zone: str | None = "web_unlocker1"):
    sleeps: list[float] = []
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        answer = answers[min(len(calls), len(answers)) - 1]
        if isinstance(answer, Exception):
            raise answer
        return answer

    async def sleep(seconds: float) -> None:
        sleeps.append(round(seconds, 4))

    client = BrightDataClient(
        "k", unlocker_zone=zone, retries=retries, sleep=sleep, rand=lambda lo, hi: hi,
        client=httpx.AsyncClient(base_url="https://api.brightdata.test",
                                 transport=httpx.MockTransport(handler)))
    return client, sleeps, calls


def _scrape(client: BrightDataClient):
    return asyncio.run(client.scrape_dataset("gd_x", [{"url": "https://example.org"}]))


def test_network_errors_back_off_linearly_with_jitter() -> None:
    # scrape_dataset never resends on a network error (a resent scrape is billed twice);
    # idempotent reads such as snapshot progress do retry.
    err = httpx.ConnectError("down")
    client, sleeps, calls = _client([err, err, httpx.Response(200, json={"status": "ready"})])
    assert asyncio.run(client.snapshot_progress("sd_x")) == {"status": "ready"}
    assert sleeps == [0.47, 0.72] and len(calls) == 3  # 0.25*n + 0.22
    client, sleeps, calls = _client([err])
    with pytest.raises(BrightDataError, match="network error"):
        _scrape(client)
    assert len(calls) == 1 and sleeps == []


@pytest.mark.parametrize("status", [429, 408, 500, 502, 503, 504])
def test_retryable_statuses_back_off_quadratically(status: int) -> None:
    client, sleeps, _ = _client([httpx.Response(status), httpx.Response(status),
                                 httpx.Response(200, json=[])])
    _scrape(client)
    assert sleeps == [0.58, 1.54]  # 0.32*n^2 + 0.26


def test_at_most_two_retries_then_error() -> None:
    client, sleeps, calls = _client([httpx.Response(503)], retries=5)
    assert client.retries == 2
    with pytest.raises(BrightDataError, match="HTTP 503"):
        _scrape(client)
    assert len(calls) == 3 and len(sleeps) == 2


def test_retry_after_is_honoured_and_capped() -> None:
    client, sleeps, _ = _client([httpx.Response(429, headers={"Retry-After": "5"}),
                                 httpx.Response(429, headers={"Retry-After": "120"}),
                                 httpx.Response(200, json=[])])
    _scrape(client)
    assert sleeps == [5.0, 30.0]
    now = datetime(2026, 10, 24, 20, 0, tzinfo=timezone.utc)
    assert retry_after_seconds(format_datetime(now + timedelta(seconds=12)), now) == 12.0
    assert retry_after_seconds("not a date") is None and retry_after_seconds(None) is None


def test_cooldown_and_no_peers_wait_15_then_30() -> None:
    client, sleeps, _ = _client([httpx.Response(502, text='{"error":"no_peers"}'),
                                 httpx.Response(503, text="zone in cooldown"),
                                 httpx.Response(200, json=[])])
    _scrape(client)
    assert sleeps == [15.0, 30.0]


CHALLENGE = "<html><head><title>Just a moment...</title></head><body>Verify you are human</body>"


@pytest.mark.parametrize(("html", "reason"), [
    ("<title>Attention Required! | Captcha</title>", "captcha"),
    (CHALLENGE, "verify you are human"),
    ("<body>Access Denied - You don't have permission</body>", "access denied"),
    ("<body>Our systems have detected unusual traffic</body>", "unusual traffic"),
    ('<script src="/cdn-cgi/challenge-platform/h/b/orchestrate"></script>', "challenge-platform"),
    ('<form id="cf-chl-widget"></form>', "cf-chl"),
    ("<p>protected by cloudflare and datadome</p>", "cloudflare+datadome"),
])
def test_block_patterns(html: str, reason: str) -> None:
    assert block_reason(html) == reason


def test_one_vendor_alone_or_late_mention_is_not_a_block() -> None:
    assert block_reason("<p>served by akamai</p><p>hotels</p>") is None
    assert block_reason("<p>hotels</p>" + "x" * 5000 + "captcha") is None
    for sample in (ROOT / "lodging" / "data").glob("*.html"):
        assert block_reason(sample.read_text(encoding="utf-8")) is None, sample
    for sample in (ROOT / "flights" / "data").glob("*.html"):
        assert block_reason(sample.read_text(encoding="utf-8")) is None, sample


def test_unlock_raises_unlocker_blocked_after_http_success() -> None:
    client, _, _ = _client([httpx.Response(200, text=CHALLENGE)])
    with pytest.raises(BrightDataError, match=r"^unlocker_blocked:verify you are human$"):
        asyncio.run(client.unlock("https://www.example.org/hotels"))


def test_connectors_report_a_block_as_degraded_never_as_an_empty_price() -> None:
    from conferge.flights.unlocker_provider import GoogleFlightsUnlockerProvider
    from conferge.lodging.models import LodgingQuery
    from conferge.lodging.service import LodgingService
    from conferge.lodging.unlocker import UnlockerHotelsSource

    q = LodgingQuery(check_in=date(2026, 10, 27), check_out=date(2026, 10, 30), adults=2,
                     verify_top=0)
    client, _, _ = _client([httpx.Response(200, text=CHALLENGE)])
    result = asyncio.run(UnlockerHotelsSource(client, sites=["hilton", "kayak"]).search(q))
    assert result.items == [] and result.run_report.status == "degraded"
    assert all("unlocker_blocked:" in e for e in result.run_report.errors)
    found = asyncio.run(LodgingService({"unlocker": UnlockerHotelsSource(client, sites=["hilton"])},
                                       fallback_sources={}).search(q))
    assert found.envelope.items == []  # no stay with a null price from a bot wall

    client, _, _ = _client([httpx.Response(200, text=CHALLENGE)])
    offers, rep = asyncio.run(GoogleFlightsUnlockerProvider(client).search_round_trip(
        "JFK", "SFO", date(2026, 10, 27), date(2026, 10, 30)))
    assert offers == [] and rep.status == "degraded"
    assert "unlocker_blocked:verify you are human" in rep.errors[0]
