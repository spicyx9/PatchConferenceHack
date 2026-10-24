"""Bright Data Web Unlocker flight search pages (zone from BRIGHTDATA_UNLOCKER_ZONE).

Google Flights (one fetch per date pair, all New York airports): results are in
``AF_initDataCallback({key: 'ds:1', ... data:[...]})``; ``data[2][0]`` best and ``data[3][0]``
other itineraries; segment [3]/[6] IATA, [8]/[10] [h, m], [20]/[21] [y, m, d],
[22] [carrier, number]. Times are airport-local. The page lists outbound legs only and its
price is the round-trip total from that outbound: the contract cannot hold a round trip
without its return slice, so the offer is ``one_way`` (outbound), ``total_price=None`` and
the observed round-trip total is kept verbatim in ``raw_price_text``. Nothing is invented.
Kayak: Bright Data refuses it without KYC (the client raises), so it is not wired.
"""

from __future__ import annotations

import asyncio
import base64
import json
import re
from collections.abc import Callable
from datetime import date, datetime, timezone
from typing import Any
from urllib.parse import parse_qs, quote, urlparse

from conferge.core.brightdata import BrightDataClient
from conferge.core.schemas import FlightOffer, RunReport, SourceEvidence
from conferge.flights.normalize import (
    NormalizationError,
    RawOffer,
    RawSegment,
    RawSlice,
    build_offer,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


_DS1 = re.compile(r"AF_initDataCallback\(\{key: 'ds:1'.*?data:(.*?), sideChannel", re.S)
_ARIA = re.compile(r'aria-label="From ([0-9,]+) ([A-Za-z ]+?) (round trip total|one way)\.[^"]*')
_CURRENCY_WORDS = {"US dollars": "USD", "euros": "EUR", "British pounds": "GBP"}
_TOKEN_CCY = re.compile(rb"\x1a\x03([A-Z]{3})")

BRIGHTDATA_ERROR = re.compile(r"^\s*(Residential Failed|Request Failed|[A-Za-z ]+Failed \()", re.I)


def detect_block(html: str) -> str | None:
    """Reason string when the body is a Bright Data refusal / empty, else None."""
    if not html or not html.strip():
        return "empty body"
    if BRIGHTDATA_ERROR.match(html) and len(html) < 2000:
        return html.strip()[:300]
    return None


def _hm(value: Any) -> tuple[int, int] | None:
    if not isinstance(value, list) or not value:
        return None
    h = value[0] or 0
    m = value[1] if len(value) > 1 and value[1] is not None else 0
    return int(h), int(m)


def _local(date: Any, time: Any) -> str | None:
    hm = _hm(time)
    if not (isinstance(date, list) and len(date) == 3 and hm):
        return None
    y, mo, d = date
    return f"{y:04d}-{mo:02d}-{d:02d}T{hm[0]:02d}:{hm[1]:02d}:00"


def _g(seq: Any, i: int) -> Any:
    return seq[i] if isinstance(seq, list) and len(seq) > i else None


def _token_currency(token: Any) -> str | None:
    if not isinstance(token, str):
        return None
    try:
        raw = base64.b64decode(token + "=" * (-len(token) % 4))
    except (ValueError, TypeError):
        return None
    m = _TOKEN_CCY.search(raw)
    return m.group(1).decode() if m else None


def _page_scope_currency(html: str, url: str) -> tuple[str, str | None]:
    scopes = {m.group(3) for m in _ARIA.finditer(html)}
    words = {m.group(2) for m in _ARIA.finditer(html)}
    scope = "unknown"
    if scopes == {"round trip total"}:
        scope = "round_trip_total"
    elif scopes == {"one way"}:
        scope = "one_way"
    ccy = None
    if len(words) == 1:
        ccy = _CURRENCY_WORDS.get(next(iter(words)))
    if ccy is None:
        q = parse_qs(urlparse(url).query).get("curr")
        ccy = q[0].upper() if q else None
    return scope, ccy


def _segment(seg: list) -> dict:
    fn = _g(seg, 22) or []
    return {
        "origin": _g(seg, 3),
        "destination": _g(seg, 6),
        "departure_local": _local(_g(seg, 20), _g(seg, 8)),
        "arrival_local": _local(_g(seg, 21), _g(seg, 10)),
        "carrier": _g(fn, 0),
        "flight_number": f"{_g(fn, 0)}{_g(fn, 1)}" if _g(fn, 0) and _g(fn, 1) else None,
    }


def parse_google_flights(html: str, url: str) -> list[dict]:
    if detect_block(html):
        return []
    scope, page_ccy = _page_scope_currency(html, url)
    m = _DS1.search(html)
    out: list[dict] = []
    if m:
        try:
            data = json.loads(m.group(1))
        except json.JSONDecodeError:
            data = None
        seen: set[tuple] = set()
        for bucket in (2, 3):
            block = _g(_g(data, bucket), 0) or []
            for it in block:
                info, price_info = _g(it, 0), _g(it, 1)
                segs = [_segment(s) for s in (_g(info, 2) or []) if isinstance(s, list)]
                if not segs:
                    continue
                amount = _g(_g(price_info, 0), 1)
                price = str(amount) if isinstance(amount, (int, float)) else None
                ccy = _token_currency(_g(price_info, 1)) or page_ccy
                key = (tuple((s["flight_number"], s["departure_local"]) for s in segs), price)
                if key in seen:
                    continue
                seen.add(key)
                out.append({
                    "direction": "outbound",  # results page lists outbound legs only
                    "segments": segs,
                    "price": price,
                    "currency": ccy if price else None,
                    "price_scope": scope if price else "unknown",
                    "url": url,
                    "price_source": "AF_initDataCallback ds:1 it[1][0][1]" if price else None,
                })
    if out:
        return out
    # Fallback: aria-labels only (no flight numbers / airport codes).
    for a in _ARIA.finditer(html):
        carrier = re.search(r"flight with ([^.]+)\.", a.group(0))
        out.append({
            "direction": "outbound", "segments": [],
            "carrier_text": carrier.group(1) if carrier else None,
            "price": a.group(1).replace(",", ""),
            "currency": _CURRENCY_WORDS.get(a.group(2)),
            "price_scope": {"round trip total": "round_trip_total", "one way": "one_way"}[a.group(3)],
            "url": url, "price_source": "aria-label",
        })
    return out


PROVIDER = "brightdata_unlocker_google_flights"


def google_flights_url(departure: date, return_date: date) -> str:
    q = f"Flights from NYC to SFO on {departure} through {return_date}"
    return f"https://www.google.com/travel/flights?q={quote(q)}&curr=USD&hl=en"


class GoogleFlightsUnlockerProvider:
    """One Unlocker fetch per (departure, return) shared by every airport pair."""

    def __init__(self, client: BrightDataClient | None = None, *, timeout: float = 120.0,
                 clock: Callable[[], datetime] = _now) -> None:
        self.client = client if client is not None else BrightDataClient.from_env()
        self.timeout = timeout
        self.clock = clock
        self._pages: dict[tuple[date, date], asyncio.Task[tuple[list[dict], datetime, str]]] = {}

    async def _page(self, departure: date, return_date: date) -> tuple[list[dict], datetime, str]:
        url = google_flights_url(departure, return_date)
        html = await asyncio.wait_for(self.client.unlock(url), self.timeout)
        return parse_google_flights(html, url), self.clock(), url

    def _report(self, started: datetime, status: str, *, fetched: int = 0, errors=None,
                warnings=None) -> RunReport:
        return RunReport(provider=PROVIDER, started_at=started,
                         finished_at=max(self.clock(), started), status=status,
                         termination="exhausted" if status == "ok" else "error",
                         source_mode="live", fetched_count=fetched, unique_count=fetched,
                         errors=errors or [], warnings=warnings or [])

    async def search_round_trip(self, origin: str, destination: str, departure: date,
                                return_date: date, *, adults: int = 1, cabin: str = "economy",
                                ) -> tuple[list[FlightOffer], RunReport]:
        started = self.clock()
        if not self.client.unlocker_zone or not getattr(self.client, "_api_key", None):
            return [], self._report(started, "failed",
                                    errors=["Web Unlocker not configured (key or zone missing)"])
        if adults != 1 or cabin != "economy":
            return [], self._report(started, "failed",
                                    errors=["Google Flights page URL covers 1 adult economy only"])
        key = (departure, return_date)
        if key not in self._pages:
            self._pages[key] = asyncio.ensure_future(self._page(departure, return_date))
        try:
            rows, collected_at, url = await asyncio.shield(self._pages[key])
        except Exception as exc:  # noqa: BLE001 - refusal, timeout, transport: visible failure
            return [], self._report(started, "failed", errors=[f"{type(exc).__name__}: {exc}"[:200]])
        offers, warnings = offers_from_rows(rows, url, collected_at, self.client.unlocker_zone,
                                            origin=origin, destination=destination)
        status = "ok" if offers else "failed"
        return offers, self._report(started, status, fetched=len(offers),
                                    errors=[] if offers else [f"no itinerary {origin}-{destination}"],
                                    warnings=warnings)


def offers_from_rows(rows: list[dict], url: str, collected_at: datetime, zone: str | None, *,
                     origin: str | None = None, destination: str | None = None,
                     ) -> tuple[list[FlightOffer], list[str]]:
    """Parsed Google Flights rows -> outbound offers; the round-trip total stays verbatim."""
    offers: list[FlightOffer] = []
    warnings: list[str] = []
    for row in rows:
        segs = row.get("segments") or []
        if not segs or (origin and segs[0]["origin"] != origin) or (
                destination and segs[-1]["destination"] != destination):
            continue
        evidence = [SourceEvidence(provider=PROVIDER, source_mode="live", source_url=url,
                                   collected_at=collected_at,
                                   raw_ref=f"unlocker:{zone}:google_flights")]
        raw = RawOffer(
            provider=PROVIDER, trip_type="one_way",
            slices=[RawSlice(segments=[RawSegment(
                origin=s["origin"], destination=s["destination"],
                departure=s["departure_local"], arrival=s["arrival_local"],
                marketing_carrier=s["carrier"], flight_number=s["flight_number"],
            ) for s in segs])],
            price=None, booking_url=url, booking_url_type="google_flights_search",
            evidence=evidence,
            warnings=["outbound_only: Google lists the return after an outbound is chosen"],
        )
        try:
            offer = build_offer(raw, collected_at)
        except NormalizationError as exc:
            warnings.append(f"normalization_failed: {exc}")
            continue
        if row.get("price"):
            scope = "round trip total" if row.get("price_scope") == "round_trip_total" else "scope unknown"
            offer = offer.model_copy(update={
                "raw_price_text": f"{row['price']} {row.get('currency') or ''} {scope}".strip(),
                "warnings": [*offer.warnings, "round_trip_total_not_split: observed price "
                             "kept in raw_price_text, not as a one-way total_price"],
            })
        offers.append(offer)
    return offers, warnings
