"""Refresh via Bright Data (Data pipeline panel button): two real calls, never at startup.

1. Web Unlocker on the Google Flights page NYC -> SFO 2026-10-27 / 2026-10-30 (the existing
   fetch and parser): offers live, collected_at = now; the shown flight becomes the cheapest
   live round trip.
2. SERP (brd_json=1) ``site:linkedin.com/in "<speaker>" <company>`` for a top-5 speaker.
Each call: 20 s, one attempt (client retries=0), no dataset. A failed call is reported with
its reason and changes nothing: the cache stays on screen.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Callable
from datetime import date, datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from conferge.api.data import DemoData, DomainSlice
from conferge.core.brightdata import BrightDataClient
from conferge.core.schemas import FlightOffer, RunReport
from conferge.core.settings import env_value
from conferge.flights.round_trip_total import trip_price
from conferge.flights.unlocker_provider import (
    PROVIDER as UNLOCKER_FLIGHTS,
)
from conferge.flights.unlocker_provider import (
    google_flights_url,
    offers_from_rows,
    parse_google_flights,
)
from conferge.integration.pipeline_view import row
from conferge.integration.stays_flights import pick_flights

TIMEOUT = 20.0
DEPART, RETURN = date(2026, 10, 27), date(2026, 10, 30)
LOCAL = ZoneInfo("America/Los_Angeles")


def make_client(http: httpx.AsyncClient | None = None) -> BrightDataClient:
    """One attempt, 20 s: retries=0 and an HTTP client timeout of TIMEOUT."""
    return BrightDataClient(
        env_value("BRIGHTDATA_API_KEY") or None,
        serp_zone=env_value("BRIGHTDATA_SERP_ZONE") or None,
        unlocker_zone=env_value("BRIGHTDATA_UNLOCKER_ZONE") or None,
        client=http or httpx.AsyncClient(base_url="https://api.brightdata.com", timeout=TIMEOUT),
        retries=0)


def _cheapest(offers: list[FlightOffer]) -> FlightOffer | None:
    priced = [o for o in offers if trip_price(o) is not None]
    return min(priced, key=lambda o: (trip_price(o), o.id)) if priced else None


def _hhmm(at: datetime | None) -> str:
    return at.astimezone(LOCAL).strftime("%H:%M") if at else "unknown time"


async def _flights(client: BrightDataClient, now: Callable[[], datetime]) -> list[FlightOffer]:
    url = google_flights_url(DEPART, RETURN)
    html = await asyncio.wait_for(client.unlock(url), TIMEOUT)
    offers, _ = offers_from_rows(parse_google_flights(html, url), url, now(), client.unlocker_zone)
    return offers


def linkedin_links(text: str) -> list[str]:
    """linkedin.com/in/ URLs from brd_json organic results, or from the HTML page when the
    SERP zone answered raw HTML (same fallback as people.crunchbase.parse_serp)."""
    from conferge.people.crunchbase import _HREF_RE, _SCRIPT_RE, _unwrap_google

    links: list[str] = []
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        data = None
    if isinstance(data, dict):
        links = [i.get("link") or i.get("url") for i in (data.get("organic") or [])
                 if isinstance(i, dict)]
    else:
        links = [_unwrap_google(h) for h in _HREF_RE.findall(_SCRIPT_RE.sub(" ", text))]
    out: list[str] = []
    for link in links:
        if isinstance(link, str) and "linkedin.com/in/" in link:
            clean = link.split("?")[0].rstrip("/")
            if clean not in out:
                out.append(clean)
    return out


async def _linkedin(client: BrightDataClient, name: str, company: str | None) -> list[str]:
    from conferge.people.crunchbase import serp_json

    query = f'site:linkedin.com/in "{name}" {company or ""}'.strip()
    return linkedin_links(await asyncio.wait_for(serp_json(client, query), TIMEOUT))


def _report(provider: str, started: datetime, now: datetime, *, ok: bool, records: int,
            error: str | None, warnings: list[str]) -> RunReport:
    return RunReport(provider=provider, started_at=started, finished_at=now,
                     status="ok" if ok else "failed", termination="exhausted" if ok else "error",
                     source_mode="live", fetched_count=records, unique_count=records,
                     errors=[error] if error else [], warnings=warnings)


async def refresh(data: DemoData, speaker: tuple[str, str | None] | None, *,
                  client: BrightDataClient | None = None,
                  now: Callable[[], datetime] = lambda: datetime.now(timezone.utc)) -> dict[str, Any]:
    """Run both calls, update ``data`` only with what succeeded, return the panel result."""
    own = client is None
    client = client or make_client()
    started, t0 = now(), time.perf_counter()
    cached = _cheapest(list(data.flights))
    calls: list[Any] = [_flights(client, now)]
    if speaker:
        calls.append(_linkedin(client, *speaker))
    try:
        results = await asyncio.gather(*calls, return_exceptions=True)
    finally:
        if own:
            await client.aclose()
    seconds = round(time.perf_counter() - t0, 1)
    lines: list[str] = []
    errors: list[str] = []
    records = 0

    flights = results[0]
    if isinstance(flights, BaseException) or not flights:
        reason = (f"{type(flights).__name__}: {flights}"[:200] if isinstance(flights, BaseException)
                  else "no itinerary parsed from the page")
        errors.append(f"Flights via Web Unlocker failed: {reason}; cached flights kept")
        data.pipeline.append(row("flights", _report(UNLOCKER_FLIGHTS, started, now(), ok=False,
                                                    records=0, error=reason, warnings=[])))
    else:
        records += len(flights)
        live = _cheapest(flights)
        was = (f"{trip_price(cached)} USD cached at {_hhmm(cached.collected_at)}"
               if cached and trip_price(cached) is not None else "no cached price")
        now_price = trip_price(live) if live else None
        same = cached is not None and now_price is not None and now_price == trip_price(cached)
        lines.append(f"Flights: cheapest round trip {was} → "
                     + ("unchanged" if same else f"{now_price} USD live now"))
        picked = pick_flights(flights)
        if picked:
            data.flights = picked
            data.domains["flights"] = DomainSlice(
                "live", "ok", now(), [f"refreshed via Bright Data Web Unlocker: {len(flights)} "
                                      "itineraries, round-trip totals as shown"])
        data.pipeline.append(row("flights", _report(
            UNLOCKER_FLIGHTS, started, now(), ok=True, records=len(flights), error=None,
            warnings=["via Web Unlocker 1x", "refresh button"])))

    if speaker:
        found = results[1]
        if isinstance(found, BaseException):
            reason = f"{type(found).__name__}: {found}"[:200]
            errors.append(f"LinkedIn via SERP failed: {reason}")
            data.pipeline.append(row("people", _report("brightdata_serp", started, now(),
                                                       ok=False, records=0, error=reason,
                                                       warnings=[])))
        else:
            records += len(found)
            lines.append(f"LinkedIn: {speaker[0]} → " + (found[0] if found else "no profile in SERP"))
            data.pipeline.append(row("people", _report("brightdata_serp", started, now(), ok=True,
                                                       records=len(found), error=None,
                                                       warnings=["refresh button"])))
    return {"ok": not errors, "requests": len(calls), "records": records, "seconds": seconds,
            "lines": lines, "errors": errors,
            "cached_price": str(trip_price(cached)) if cached and trip_price(cached) else None,
            "live_price": (str(trip_price(_cheapest(results[0])))
                           if not isinstance(results[0], BaseException) and results[0]
                           and _cheapest(results[0]) else None)}


__all__ = ["TIMEOUT", "linkedin_links", "make_client", "refresh"]
