from __future__ import annotations

import asyncio
import threading
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx

from conferge.core.brightdata import BrightDataClient
from conferge.flights.unlocker_provider import GoogleFlightsUnlockerProvider

SAMPLE = (Path(__file__).parent / "data" / "google_flights_unlocker_sample.html").read_text(
    encoding="utf-8")


def test_one_fetch_serves_every_pair_and_never_splits_the_round_trip_total() -> None:
    hits: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            self.rfile.read(int(self.headers["Content-Length"]))
            hits.append(self.path)
            body = SAMPLE.encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    client = BrightDataClient("k", unlocker_zone="web_unlocker1", client=httpx.AsyncClient(
        base_url=f"http://127.0.0.1:{server.server_address[1]}"))
    provider = GoogleFlightsUnlockerProvider(client)

    async def run() -> list:
        pairs = [("EWR", "SFO"), ("JFK", "SFO"), ("LGA", "SFO")]
        return await asyncio.gather(*(provider.search_round_trip(o, d, date(2026, 10, 27),
                                                                  date(2026, 10, 30))
                                      for o, d in pairs))

    try:
        (ewr, ewr_rep), (jfk, _), (lga, lga_rep) = asyncio.run(run())
    finally:
        server.shutdown()
    assert len(hits) == 1  # one Web Unlocker request for the three airports
    assert [o.slices[0].segments[0].flight_number for o in ewr] == ["F94601"]
    assert [o.slices[0].segments[0].flight_number for o in jfk] == ["B6215"]
    assert lga == [] and lga_rep.status == "failed" and ewr_rep.status == "ok"
    offer = jfk[0]
    assert offer.total_price is None and offer.price_status == "unknown"
    assert offer.raw_price_text == "716 USD round trip total"
    assert offer.slices[0].segments[0].departure_at.isoformat() == "2026-10-27T10:00:00-04:00"
    assert offer.evidence[0].raw_ref == "unlocker:web_unlocker1:google_flights"
