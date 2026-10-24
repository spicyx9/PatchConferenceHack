from __future__ import annotations

import asyncio
import json
import threading
from datetime import date, datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx

from conferge.core.brightdata import BrightDataClient
from conferge.core.schemas import DiscoveryResult
from conferge.lodging._common import report
from conferge.lodging.models import LodgingQuery
from conferge.lodging.normalize import normalize
from conferge.lodging.service import LodgingService
from conferge.lodging.unlocker import UnlockerHotelsSource

SAMPLE = (Path(__file__).parent / "data" / "hilton_unlocker_sample.html").read_text(encoding="utf-8")
REFUSAL = ("Residential Failed (bad_endpoint): Requested site is not available for immediate "
           "residential (no KYC) access mode. fill in the KYC form: https://brightdata.com/cp/kyc")
Q = LodgingQuery(check_in=date(2026, 10, 27), check_out=date(2026, 10, 30), adults=2,
                 limit=5, verify_top=0)


def _server(pages: dict[str, str]) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            host = httpx.URL(body["url"]).host
            text = next((v for k, v in pages.items() if k in host), REFUSAL).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(text)))
            self.end_headers()
            self.wfile.write(text)

        def log_message(self, *_: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def test_unlocker_hilton_names_without_dated_price_and_kyc_refusals_reported() -> None:
    server = _server({"hilton.com": SAMPLE})
    client = BrightDataClient("k", unlocker_zone="web_unlocker1", client=httpx.AsyncClient(
        base_url=f"http://127.0.0.1:{server.server_address[1]}"))
    try:
        result = asyncio.run(UnlockerHotelsSource(client).search(Q))
    finally:
        server.shutdown()
    rep = result.run_report
    assert rep.status == "degraded" and len(result.items) == 3
    assert {r.payload["site"] for r in result.items} == {"hilton"}
    assert all(r.request_id == "unlocker:web_unlocker1:hilton" for r in result.items)
    assert sum("KYC required" in e for e in rep.errors) == 4  # kayak, hotels.com, expedia, marriott
    assert any("3 without a price in the HTML" in w for w in rep.warnings)
    stay = normalize(result.items[0], Q, warnings=[])
    assert stay is not None and stay.total_price is None and stay.nightly_avg is None
    assert stay.price_status == "unknown" and stay.venue and stay.venue.address


class _Fixed:
    def __init__(self, items: list, status: str = "ok") -> None:
        self.items, self.status, self.calls = items, status, 0

    async def search(self, q: LodgingQuery) -> DiscoveryResult:
        self.calls += 1
        rep = report("fake", datetime.now(timezone.utc), status=self.status,
                     termination="exhausted" if self.items else "error", fetched=len(self.items))
        return DiscoveryResult(items=self.items, run_report=rep)


def test_fallback_runs_only_when_bright_data_found_nothing() -> None:
    server = _server({"hilton.com": SAMPLE})
    client = BrightDataClient("k", unlocker_zone="z", client=httpx.AsyncClient(
        base_url=f"http://127.0.0.1:{server.server_address[1]}"))
    try:
        records = asyncio.run(UnlockerHotelsSource(client, sites=["hilton"]).search(Q)).items
    finally:
        server.shutdown()
    fallback = _Fixed([])
    found = asyncio.run(LodgingService({"unlocker": _Fixed(records)},
                                       fallback_sources={"pyairbnb": fallback}).search(Q))
    assert found.envelope.items and fallback.calls == 0
    empty = _Fixed([], status="failed")
    used = asyncio.run(LodgingService({"booking": empty},
                                      fallback_sources={"pyairbnb": fallback}).search(Q))
    assert fallback.calls == 1 and empty.calls == 1
    assert used.warnings[0].startswith("fallback used")


class _Slow:
    async def search(self, q: LodgingQuery) -> DiscoveryResult:
        await asyncio.sleep(5)
        raise AssertionError("not reached")


def test_one_slow_provider_is_a_failed_report_not_a_dead_search() -> None:
    import time

    hilton = _Fixed([])
    t0 = time.monotonic()
    found = asyncio.run(LodgingService({"slow": _Slow(), "other": hilton}, fallback_sources={},
                                       provider_timeout=0.2).search(Q))
    assert time.monotonic() - t0 < 2
    slow = next(r for r in found.envelope.reports if r.provider == "slow")
    assert slow.status == "failed" and "timeout" in slow.errors[0]
