"""Resilience tests run the real app and real providers; failures come from real sockets.

No code is mocked: FalkorDB "down" is a closed port, Bright Data errors come from a real
local HTTP server (429 or too slow), missing keys are a missing environment variable.
Tests that need the public internet (Airbnb, Google Flights) run only with
CONFERGE_LIVE_TESTS=1.
"""

from __future__ import annotations

import json
import os
import socket
import threading
import time
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest

from conferge.core.brightdata import BrightDataClient
from conferge.lodging.models import LodgingQuery

QUERY = LodgingQuery(check_in=date(2026, 10, 27), check_out=date(2026, 10, 30), adults=1,
                     currency="USD", limit=5, verify_top=0,
                     conference_id="github-universe-2026")
BD_ENV = ("BRIGHTDATA_API_KEY", "BRIGHTDATA_SERP_ZONE", "BRIGHTDATA_UNLOCKER_ZONE")
live_only = pytest.mark.skipif(os.environ.get("CONFERGE_LIVE_TESTS") != "1",
                               reason="needs the public internet; set CONFERGE_LIVE_TESTS=1")


def closed_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class FakeBrightData:
    """A real HTTP server on 127.0.0.1 answering every request with 429, or too slowly."""

    def __init__(self, mode: str) -> None:
        self.mode = mode
        self.hits: list[str] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def _answer(self) -> None:
                outer.hits.append(self.path.split("?")[0])
                length = int(self.headers.get("Content-Length") or 0)
                if length:
                    self.rfile.read(length)
                if outer.mode == "slow":
                    time.sleep(1.0)
                body = json.dumps({"error": "rate limited"} if outer.mode == "429" else []).encode()
                try:
                    self.send_response(429 if outer.mode == "429" else 200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                except (BrokenPipeError, ConnectionResetError):
                    pass  # the client gave up (timeout): expected in slow mode

            do_GET = do_POST = _answer  # noqa: N815

            def log_message(self, *_: object) -> None:
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def client(self, *, timeout: float = 5.0) -> BrightDataClient:
        return BrightDataClient("resilience-test-key",
                                client=httpx.AsyncClient(base_url=self.url, timeout=timeout))

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
