"""Refresh via Bright Data (Data pipeline panel button): two real calls, never at startup.

1. Web Unlocker on the Google Flights page NYC -> SFO 2026-10-27 / 2026-10-30 (the existing
   fetch and parser): offers live, collected_at = now; the shown flight becomes the cheapest
   live round trip.
2. SERP (brd_json=1) ``site:linkedin.com/in "<speaker>" <company>`` for a top-5 speaker.
One attempt each (client retries=0), no dataset: Web Unlocker 45 s (past it: "Bright Data
slow, cache kept"), SERP 20 s. The raw SERP answer is kept in data/probes/refresh_serp_<ts>.json
(gitignored) and read with Bright Data's real keys (organic[].link/title/description/rank);
a profile URL already in data/cache/linkedin_public.json is reported as confirmed. A failed
call is reported with its reason and changes nothing: the cache stays on screen.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Callable
from datetime import date, datetime, timezone
from pathlib import Path
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

TIMEOUT = 20.0  # SERP
UNLOCKER_TIMEOUT = 45.0  # Google Flights page through the Web Unlocker
SLOW = "Bright Data slow, cache kept"
ROOT = Path(__file__).resolve().parents[2]
PROBE_DIR = ROOT / "data" / "probes"
LINKEDIN_CACHE = ROOT / "data" / "cache" / "linkedin_public.json"
DEPART, RETURN = date(2026, 10, 27), date(2026, 10, 30)
LOCAL = ZoneInfo("America/Los_Angeles")


DEFAULT_UNLOCKER_ZONE = "web_unlocker1"
DEFAULT_SERP_ZONE = "serp_api1"


def default_zones_used() -> list[str]:
    """Zones the refresh falls back to because .env leaves them empty."""
    return [name for name, var in (("web_unlocker1", "BRIGHTDATA_UNLOCKER_ZONE"),
                                   ("serp_api1", "BRIGHTDATA_SERP_ZONE"))
            if not env_value(var)]


def make_client(http: httpx.AsyncClient | None = None) -> BrightDataClient:
    """One attempt: retries=0. With a key but no zone, the account's default zone names."""
    return BrightDataClient(
        env_value("BRIGHTDATA_API_KEY") or None,
        serp_zone=env_value("BRIGHTDATA_SERP_ZONE") or DEFAULT_SERP_ZONE,
        unlocker_zone=env_value("BRIGHTDATA_UNLOCKER_ZONE") or DEFAULT_UNLOCKER_ZONE,
        client=http or httpx.AsyncClient(base_url="https://api.brightdata.com",
                                         timeout=UNLOCKER_TIMEOUT + 5),
        retries=0)


def _cheapest(offers: list[FlightOffer]) -> FlightOffer | None:
    priced = [o for o in offers if trip_price(o) is not None]
    return min(priced, key=lambda o: (trip_price(o), o.id)) if priced else None


def _hhmm(at: datetime | None) -> str:
    return at.astimezone(LOCAL).strftime("%H:%M") if at else "unknown time"


async def _flights(client: BrightDataClient, now: Callable[[], datetime]) -> list[FlightOffer]:
    url = google_flights_url(DEPART, RETURN)
    html = await asyncio.wait_for(client.unlock(url), UNLOCKER_TIMEOUT)
    offers, _ = offers_from_rows(parse_google_flights(html, url), url, now(), client.unlocker_zone)
    return offers


def serp_organic(text: str) -> list[dict[str, Any]]:
    """Organic results with Bright Data's real keys (PR #34): link, title, description, rank."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return []
    items = data.get("organic") if isinstance(data, dict) else None
    return [{"link": i.get("link"), "title": i.get("title"), "description": i.get("description"),
             "rank": i.get("rank")} for i in items or [] if isinstance(i, dict)]


def _norm_profile(url: str | None) -> str | None:
    """https://fr.linkedin.com/in/RyanAHecht/?x=1 -> linkedin.com/in/ryanahecht"""
    if not isinstance(url, str) or "linkedin.com/in/" not in url:
        return None
    slug = url.split("linkedin.com/in/", 1)[1].split("?")[0].split("#")[0].strip("/")
    return f"linkedin.com/in/{slug.lower()}" if slug else None


def linkedin_links(text: str) -> list[str]:
    """linkedin.com/in/ URLs from the organic results (HTML answer as fallback)."""
    from conferge.people.crunchbase import _HREF_RE, _SCRIPT_RE, _unwrap_google

    links = [r["link"] for r in serp_organic(text)]
    if not links and not text.lstrip().startswith("{"):
        links = [_unwrap_google(h) for h in _HREF_RE.findall(_SCRIPT_RE.sub(" ", text))]
    out: list[str] = []
    for link in links:
        if _norm_profile(link) and link.split("?")[0].rstrip("/") not in out:
            out.append(link.split("?")[0].rstrip("/"))
    return out


def cached_profiles(path: Path = LINKEDIN_CACHE) -> dict[str, str]:
    """name (casefolded) -> cached LinkedIn URL, from the public LinkedIn cache."""
    try:
        rows = json.loads(path.read_text(encoding="utf-8")).get("profiles") or []
    except (OSError, ValueError, AttributeError):
        return {}
    return {r["name"].casefold(): r["linkedin_url"] for r in rows
            if isinstance(r, dict) and r.get("name") and r.get("linkedin_url")}


def _save_serp(query: str, text: str, at: datetime, directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"refresh_serp_{at.strftime('%Y%m%dT%H%M%SZ')}.json"
    path.write_text(json.dumps({"query": query, "collected_at": at.isoformat(),
                                "organic": serp_organic(text), "raw": text}, indent=1),
                    encoding="utf-8")
    return path


async def _linkedin(client: BrightDataClient, name: str, company: str | None, *,
                    now: Callable[[], datetime], probe_dir: Path) -> dict[str, Any]:
    from conferge.people.crunchbase import serp_json

    query = f'site:linkedin.com/in "{name}" {company or ""}'.strip()
    text = await asyncio.wait_for(serp_json(client, query), TIMEOUT)
    saved = _save_serp(query, text, now(), probe_dir)
    return {"links": linkedin_links(text), "organic": len(serp_organic(text)),
            "json": text.lstrip().startswith("{"), "saved": saved.name}


def _report(provider: str, started: datetime, now: datetime, *, ok: bool, records: int,
            error: str | None, warnings: list[str]) -> RunReport:
    return RunReport(provider=provider, started_at=started, finished_at=now,
                     status="ok" if ok else "failed", termination="exhausted" if ok else "error",
                     source_mode="live", fetched_count=records, unique_count=records,
                     errors=[error] if error else [], warnings=warnings)


async def refresh(data: DemoData, speaker: tuple[str, str | None] | None, *,
                  client: BrightDataClient | None = None,
                  now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
                  probe_dir: Path = PROBE_DIR, linkedin_cache: Path = LINKEDIN_CACHE,
                  ) -> dict[str, Any]:
    """Run both calls, update ``data`` only with what succeeded, return the panel result."""
    own = client is None
    notes = [f"default zones: {', '.join(default_zones_used())}"] if own and default_zones_used() else []
    client = client or make_client()
    started, t0 = now(), time.perf_counter()
    if not getattr(client, "_api_key", None):
        if own:
            await client.aclose()
        # Checked before any zone: without a key nothing is sent.
        return {"ok": False, "requests": 0, "records": 0, "seconds": 0.0, "lines": [],
                "errors": ["BRIGHTDATA_API_KEY missing: nothing sent, cache kept"], "slow": [],
                "notes": [], "cached_price": None, "live_price": None}
    sent: list[str] = []

    async def count(request: httpx.Request) -> None:
        sent.append(request.url.path)

    http = client._client
    http.event_hooks = {**http.event_hooks, "request": [*http.event_hooks.get("request", []), count]}
    cached = _cheapest(list(data.flights))
    calls: list[Any] = [_flights(client, now)]
    if speaker:
        calls.append(_linkedin(client, *speaker, now=now, probe_dir=probe_dir))
    try:
        results = await asyncio.gather(*calls, return_exceptions=True)
    finally:
        if own:
            await client.aclose()
    seconds = round(time.perf_counter() - t0, 1)
    lines: list[str] = []
    errors: list[str] = []
    slow: list[str] = []
    records = 0

    flights = results[0]
    if isinstance(flights, (asyncio.TimeoutError, TimeoutError)) or (
            isinstance(flights, Exception) and str(flights).endswith(": timeout")):
        slow.append(f"{SLOW} (Web Unlocker over {UNLOCKER_TIMEOUT:.0f} s)")
        data.pipeline.append(row("flights", _report(UNLOCKER_FLIGHTS, started, now(), ok=False,
                                                    records=0, error=SLOW, warnings=[])))
    elif isinstance(flights, BaseException) or not flights:
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
            links = found["links"]
            records += len(links)
            known = _norm_profile(cached_profiles(linkedin_cache).get(speaker[0].casefold()))
            if known and known in {_norm_profile(u) for u in links}:
                lines.append("LinkedIn: 1 profile confirmed (cached)")
            elif links:
                lines.append(f"LinkedIn: {speaker[0]} → {links[0]}"
                             + (" (differs from the cached URL)" if known else ""))
            else:
                lines.append(f"LinkedIn: {speaker[0]} → no profile in SERP "
                             f"({found['organic']} organic results"
                             f"{'' if found['json'] else ', answer not JSON'})")
            data.pipeline.append(row("people", _report(
                "brightdata_serp", started, now(), ok=True, records=len(links), error=None,
                warnings=["refresh button", f"raw answer kept in data/probes/{found['saved']}"])))
    # requests: HTTP requests actually sent to Bright Data, not the calls attempted.
    return {"ok": not errors and not slow, "requests": len(sent), "records": records,
            "seconds": seconds, "lines": lines, "errors": errors, "slow": slow, "notes": notes,
            "cached_price": str(trip_price(cached)) if cached and trip_price(cached) else None,
            "live_price": (str(trip_price(_cheapest(results[0])))
                           if not isinstance(results[0], BaseException) and results[0]
                           and _cheapest(results[0]) else None)}


__all__ = ["TIMEOUT", "UNLOCKER_TIMEOUT", "cached_profiles", "linkedin_links", "make_client",
           "refresh", "serp_organic"]
