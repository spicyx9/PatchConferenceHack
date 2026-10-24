"""Block matrix: can each site the connectors use be reached by a plain fetch, or only via Bright Data?

The site list is derived from the code (domains and Bright Data dataset ids in conferge/events,
people, lodging, flights, integration, plus the Web Unlocker search targets and Google Search
for SERP). Each URL is a real search or detail page built the way the connector builds it.

For every site, three attempts run in parallel, 20 s timeout, one request each, no retry:
  (a) httpx, default User-Agent   (b) httpx, browser User-Agent
  (c) Bright Data Web Unlocker, zone ``web_unlocker1``
Classification:
  ok        HTTP 200 and the site's content marker found (a price, an event name, a person name)
  shell_js  HTTP 200 but no marker (JavaScript shell, consent page, empty results)
  blocked   401/403/429/999, captcha or bot wall, redirect to login, Bright Data refusal (KYC)
  error     timeout, network error, other HTTP status
The marker is a precise string or pattern per site, never the page size.

Column (d) "Bright Data dataset" is filled only from snapshots that already exist (no new
trigger): ``GET /datasets/v3/progress/<id>`` then, when ready, ``GET /datasets/v3/snapshot/<id>``
to count records (rows carrying ``error``/``error_code`` are not records). Nothing but counts and
error codes is kept. ok when records > 0; pending while the snapshot is still running.

Writes docs/BLOCK_MATRIX.md and data/block_matrix.json (read by the Data pipeline panel).
Run: ``uv run python scripts/probes/block_matrix.py`` (BRIGHTDATA_API_KEY from env or .env).
``--datasets-only`` keeps the last fetch results and only re-reads the dataset snapshots.
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from conferge.core.brightdata import BrightDataClient, BrightDataError  # noqa: E402
from conferge.core.settings import env_value  # noqa: E402
from conferge.events.official.rainfocus import CATALOG_URL  # noqa: E402
from conferge.flights.brightdata_provider import DATASET_ID as DS_GOOGLE_FLIGHTS  # noqa: E402
from conferge.flights.unlocker_provider import google_flights_url  # noqa: E402
from conferge.lodging._common import (  # noqa: E402
    DATASET_AIRBNB,
    DATASET_BOOKING_SEARCH,
    DATASET_GOOGLE_HOTELS,
)
from conferge.lodging.models import LodgingQuery  # noqa: E402
from conferge.lodging.unlocker import SEARCH_URLS  # noqa: E402

ZONE = "web_unlocker1"
TIMEOUT = 20.0
CHECK_IN, CHECK_OUT = date(2026, 10, 27), date(2026, 10, 30)
BROWSER_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36")
PRICE = r"(?:US\$|\$)\s?\d{2,4}(?:[.,]\d{2})?"
BLOCK_SIGNS = re.compile(
    r"px-captcha|g-recaptcha|h-captcha|hcaptcha\.com|captcha-delivery|datadome|"
    r"verify you are (?:a )?human|are you a robot|unusual traffic|access denied|"
    r"request blocked|cf-chl|just a moment\.\.\.|/authwall|sign in to view", re.I)
LOGIN_URL = re.compile(r"/(?:login|signin|sign-in|authwall|checkpoint|uas/login)", re.I)


@dataclass
class Site:
    name: str
    connector: str
    url: str
    marker: str
    """Regex (precise string or price pattern) that proves useful content."""
    marker_desc: str
    bright_data: str = ""
    """Bright Data API the connector uses for this site, if any (dataset id, unlocker, serp)."""


def sites() -> list[Site]:
    q = LodgingQuery(check_in=CHECK_IN, check_out=CHECK_OUT, adults=2, currency="USD")
    unlocker = [
        Site(label, "conferge/lodging/unlocker.py", SEARCH_URLS[key](q), PRICE, "a nightly price",
             f"Web Unlocker ({key})")
        for key, label in (("kayak", "Kayak"), ("hotels_com", "Hotels.com"), ("expedia", "Expedia"),
                           ("marriott", "Marriott"), ("hilton", "Hilton"))
    ]
    return [
        Site("githubuniverse.com", "conferge/events/official/normalize.py", "https://githubuniverse.com/",
             r"Fort Mason", "venue name 'Fort Mason'", "Web Unlocker target"),
        Site("RainFocus session catalog", "conferge/events/official/rainfocus.py",
             CATALOG_URL,
             r"Levi Strauss", "session '17 agents, one SDLC: How Levi Strauss...'"),
        Site("Luma event page", "conferge/events/luma/source.py", "https://luma.com/x7lmea3h",
             r"Agentic Hacking Challenge", "event 'Breakfast & Agentic Hacking Challenge'"),
        Site("Luma discover API", "conferge/events/luma/source.py",
             "https://api2.luma.com/discover/get-paginated-events?latitude=37.806&longitude=-122.432"
             "&pagination_limit=20", r'"api_id":\s?"evt-', "an event id (evt-...) in the JSON"),
        Site("Partiful event page", "conferge/events/partiful/source.py",
             "https://partiful.com/e/h6YYc5rG42JsJ9zHCjMX", r"cine cue", "event 'cine cue presents'"),
        Site("Eventbrite event page", "conferge/events/eventbrite/source.py",
             "https://www.eventbrite.com/e/ai-security-securing-the-age-of-autonomous-ai-tickets-2003316175609",
             r"(?i)securing the age of autonomous ai", "event 'AI Security: Securing the Age of Autonomous AI'"),
        Site("conferenceparties.com", "conferge/events/aggregators/conferenceparties.py",
             "https://conferenceparties.com/github26/", r"Ship It Afterparty", "event 'Ship It Afterparty'"),
        Site("Facebook Events", "conferge/events/discovery/facebook.py",
             "https://www.facebook.com/events/search/?q=github%20universe%20san%20francisco",
             r"facebook\.com\\?/events\\?/\d{8,}|\"/events/\d{8,}", "a link to an event page (/events/<id>)",
             "dataset gd_m14sd0to1jz48ppm51"),
        Site("Google Search (SERP)", "conferge/events/discovery/serp.py",
             "https://www.google.com/search?q=github+universe+2026+side+events&gl=us",
             r"githubuniverse\.com", "result linking githubuniverse.com", "SERP zone"),
        Site("LinkedIn public profile", "conferge/people/linkedin.py",
             "https://www.linkedin.com/in/pamela-s-fox/", r"Pamela Fox", "person 'Pamela Fox'",
             "dataset gd_l1viktl72bvl7bjuj0"),
        Site("GitHub API", "conferge/people/enrich.py", "https://api.github.com/users/pamelafox",
             r"Pamela Fox", "person 'Pamela Fox'"),
        Site("Booking", "conferge/lodging/booking.py",
             "https://www.booking.com/searchresults.html?ss=San+Francisco&checkin=2026-10-27"
             "&checkout=2026-10-30&group_adults=2&no_rooms=1&selected_currency=USD",
             PRICE, "a nightly price", f"dataset {DATASET_BOOKING_SEARCH}"),
        Site("Google Hotels", "conferge/lodging/google_hotels.py",
             "https://www.google.com/travel/search?q=hotels%20in%20San%20Francisco&hl=en&gl=us&curr=USD",
             PRICE, "a nightly price", f"dataset {DATASET_GOOGLE_HOTELS}"),
        Site("Airbnb", "conferge/lodging/airbnb.py",
             "https://www.airbnb.com/s/San-Francisco--CA/homes?checkin=2026-10-27&checkout=2026-10-30&adults=2",
             PRICE, "a price", f"dataset {DATASET_AIRBNB}"),
        *unlocker,
        Site("Google Flights", "conferge/flights/unlocker_provider.py, conferge/flights/brightdata_provider.py",
             google_flights_url(CHECK_IN, CHECK_OUT), PRICE, "a fare",
             f"Web Unlocker + dataset {DS_GOOGLE_FLIGHTS}"),
        Site("SerpApi Google Flights", "conferge/flights/serpapi_provider.py",
             "https://serpapi.com/search.json?engine=google_flights&departure_id=JFK&arrival_id=SFO"
             "&outbound_date=2026-10-27&return_date=2026-10-30&currency=USD",
             r'"best_flights"|"other_flights"', "flight results in the JSON (API key required)"),
    ]


# Existing snapshots per site (triggered earlier by the connectors); read-only here.
DATASET_SNAPSHOTS: dict[str, list[str]] = {
    "Booking": ["sd_mvmq28k3vcsg9t28n"],
    "Airbnb": ["sd_mvmpvf5hy3yeo7ffq"],
    "LinkedIn public profile": ["sd_mvmpuno1cydgpjvik", "sd_mvmpunm2ess6r1ual"],
    "Google Hotels": ["sd_mvmqtmqu2f5qp48xvg"],
    "Google Flights": ["sd_mvmr6icq29xwep13p7"],
}
# Context the API does not carry, reported by the team (Bright Data email).
DATASET_NOTES = {
    "sd_mvmqtmqu2f5qp48xvg": "Bright Data provider outage at 18:12 UTC, confirmed by Bright Data email",
}
KYC_PENDING = ("Kayak", "Hotels.com", "Expedia", "Marriott")

NOT_CALLED = [
    {"site": "X (x.com)", "where": "conferge/events/discovery/router.py, conferge/events/official/sessionize.py",
     "why": "only used to classify social URLs, no connector fetches it"},
    {"site": "Crunchbase", "where": "-", "why": "no connector references it"},
    {"site": "Google Maps", "where": "-", "why": "no connector references it"},
    {"site": "Sessionize", "where": "conferge/events/official/sessionize.py",
     "why": "needs an endpoint id; GitHub Universe 2026 publishes none, so no real page to test"},
]


def _classify(status: int | None, text: str, final_url: str, marker: str) -> tuple[str, str]:
    if status == 200 and re.search(marker, text):
        return "ok", "marker found"
    if status in {401, 403, 407, 429, 451, 999}:
        return "blocked", f"HTTP {status}"
    if status == 202 and BLOCK_SIGNS.search(text) is None and len(text) < 20_000:
        return "blocked", "HTTP 202 bot challenge (empty body to solve in JavaScript)"
    if LOGIN_URL.search(final_url or ""):
        return "blocked", f"redirected to login ({final_url[:80]})"
    if status == 200 and BLOCK_SIGNS.search(text[:200_000]):
        sign = BLOCK_SIGNS.search(text[:200_000])
        return "blocked", f"bot wall: '{sign.group(0)[:40]}'" if sign else "bot wall"
    if status == 200:
        return "shell_js", "HTTP 200, marker absent"
    return "error", f"HTTP {status}"


async def _plain(site: Site, ua: str | None) -> dict[str, Any]:
    headers = {"User-Agent": ua, "Accept": "text/html,application/json;q=0.9,*/*;q=0.8",
               "Accept-Language": "en-US,en;q=0.9"} if ua else {}
    t0 = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=True, headers=headers) as client:
            resp = await client.get(site.url)
        result, detail = _classify(resp.status_code, resp.text, str(resp.url), site.marker)
        return {"class": result, "http_status": resp.status_code, "detail": detail,
                "duration_s": round(time.perf_counter() - t0, 1)}
    except (httpx.TimeoutException, asyncio.TimeoutError):
        return {"class": "error", "http_status": None, "detail": f"timeout {TIMEOUT:.0f}s",
                "duration_s": round(time.perf_counter() - t0, 1)}
    except httpx.HTTPError as exc:
        return {"class": "error", "http_status": None, "detail": f"{type(exc).__name__}: {str(exc)[:80]}",
                "duration_s": round(time.perf_counter() - t0, 1)}


async def _unlocker(site: Site, client: BrightDataClient) -> dict[str, Any]:
    t0 = time.perf_counter()
    try:
        text = await asyncio.wait_for(client.unlock(site.url), TIMEOUT)
        result, detail = _classify(200, text, site.url, site.marker)
        return {"class": result, "http_status": 200, "detail": detail,
                "duration_s": round(time.perf_counter() - t0, 1)}
    except (asyncio.TimeoutError, httpx.TimeoutException):
        return {"class": "error", "http_status": None, "detail": f"timeout {TIMEOUT:.0f}s",
                "duration_s": round(time.perf_counter() - t0, 1)}
    except BrightDataError as exc:
        text = str(exc)
        status = re.search(r"\b(4\d\d|5\d\d)\b", text)
        refused = "refused" in text.lower() or "kyc" in text.lower() or (status and status.group(1).startswith("4"))
        return {"class": "blocked" if refused else "error", "http_status": int(status.group(1)) if status else None,
                "detail": f"Bright Data: {text[:120]}", "duration_s": round(time.perf_counter() - t0, 1)}
    except httpx.HTTPError as exc:
        return {"class": "error", "http_status": None, "detail": f"{type(exc).__name__}: {str(exc)[:80]}",
                "duration_s": round(time.perf_counter() - t0, 1)}


async def dataset_cell(snapshots: list[str], client: BrightDataClient | None) -> dict[str, Any]:
    """Existing snapshots only: progress, then a record count when ready. Never triggers."""
    if not snapshots:
        return {"class": "not_run", "http_status": None, "detail": "no snapshot for this site", "duration_s": 0.0,
                "snapshots": []}
    if client is None:
        return {"class": "error", "http_status": None, "detail": "BRIGHTDATA_API_KEY not set", "duration_s": 0.0,
                "snapshots": []}
    t0 = time.perf_counter()
    found = []
    for sid in snapshots:
        entry: dict[str, Any] = {"snapshot_id": sid, "status": None, "records": None, "error_codes": []}
        try:
            progress = await asyncio.wait_for(client.snapshot_progress(sid), TIMEOUT)
            entry["status"] = progress.get("status")
            entry["dataset_id"] = progress.get("dataset_id")
            if entry["status"] == "ready":
                out = await asyncio.wait_for(client.snapshot_results(sid), TIMEOUT)
                rows = out.data if isinstance(out.data, list) else ([] if out.data is None else [out.data])
                errors = [r for r in rows if isinstance(r, dict) and (r.get("error") or r.get("error_code"))]
                entry["records"] = len(rows) - len(errors)
                entry["error_codes"] = sorted({str(r.get("error_code") or "error") for r in errors})
        except (asyncio.TimeoutError, httpx.HTTPError, BrightDataError) as exc:
            entry["status"] = f"read failed: {type(exc).__name__}"
        if sid in DATASET_NOTES:
            entry["note"] = DATASET_NOTES[sid]
        found.append(entry)
    records = sum(e["records"] or 0 for e in found)
    if records > 0:
        cls = "ok"
    elif any(e["status"] in {"running", "starting", "building"} for e in found):
        cls = "pending"
    else:
        cls = "error"
    parts = []
    for e in found:
        text = f"{e['snapshot_id']} {e['status']}"
        if e["records"] is not None:
            text += f", {e['records']} records"
        if e["error_codes"]:
            text += f", errors: {', '.join(e['error_codes'])}"
        if e.get("note"):
            text += f" ({e['note']})"
        parts.append(text)
    return {"class": cls, "http_status": None, "detail": "; ".join(parts), "records": records,
            "duration_s": round(time.perf_counter() - t0, 1), "snapshots": found}


async def probe(site: Site, client: BrightDataClient | None) -> dict[str, Any]:
    async def no_key() -> dict[str, Any]:
        return {"class": "error", "http_status": None, "detail": "BRIGHTDATA_API_KEY not set", "duration_s": 0.0}

    a, b, c, d = await asyncio.gather(_plain(site, None), _plain(site, BROWSER_UA),
                                      _unlocker(site, client) if client else no_key(),
                                      dataset_cell(DATASET_SNAPSHOTS.get(site.name, []), client))
    return {"site": site.name, "connector": site.connector, "url": site.url, "bright_data": site.bright_data,
            "marker": site.marker, "marker_desc": site.marker_desc,
            "attempts": {"plain_default_ua": a, "plain_browser_ua": b, "brightdata_unlocker": c,
                         "brightdata_dataset": d}}


def counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    def ok(r: dict[str, Any], *keys: str) -> bool:
        return any(r["attempts"].get(k, {}).get("class") == "ok" for k in keys)

    with_bd = [r for r in rows if ok(r, "brightdata_unlocker", "brightdata_dataset")]
    kyc_gain = [r["site"] for r in rows if r["site"] in KYC_PENDING and r not in with_bd]
    return {
        "n": len(rows),
        "reachable_without_brightdata": sum(ok(r, "plain_default_ua", "plain_browser_ua") for r in rows),
        "reachable_with_brightdata": len(with_bd),
        "reachable_with_unlocker_only": sum(ok(r, "brightdata_unlocker") for r in rows),
        "reachable_any_path": sum(ok(r, "plain_default_ua", "plain_browser_ua", "brightdata_unlocker",
                                     "brightdata_dataset") for r in rows),
        "kyc_pending": list(KYC_PENDING),
        "reachable_with_brightdata_if_kyc_approved": len(with_bd) + len(kyc_gain),
    }


def markdown(report: dict[str, Any]) -> str:
    c = report["counts"]
    lines = [
        "# Block matrix: plain fetch vs Bright Data",
        "",
        f"Run {report['run_at']} (UTC), timeout {report['timeout_s']:.0f} s, one request per attempt, no retry, "
        f"Bright Data Web Unlocker zone `{report['zone']}`. Generated by `scripts/probes/block_matrix.py`.",
        "",
        f"**{c['reachable_without_brightdata']} of {c['n']} sites reachable without Bright Data, "
        f"{c['reachable_with_brightdata']} of {c['n']} with** (Web Unlocker or dataset; Web Unlocker alone "
        f"{c['reachable_with_unlocker_only']} of {c['n']}; {c['reachable_any_path']} of {c['n']} by any path).",
        "",
        f"**KYC pending** ({', '.join(c['kyc_pending'])}): Web Unlocker refuses these sites until the account "
        f"KYC is approved. Once approved, and if the Unlocker then returns their marker (projection, not "
        f"measured): {c['reachable_with_brightdata_if_kyc_approved']} of {c['n']} with Bright Data.",
        "",
        f"Dataset column (d): existing snapshots only, read {report.get('datasets_read_at', report['run_at'])} "
        "(UTC), no new trigger; ok when records > 0.",
        "",
        "Classes: `ok` HTTP 200 and the content marker found; `shell_js` HTTP 200 without the marker; "
        "`blocked` 401/403/429/999, captcha or bot wall, redirect to login, Bright Data refusal; "
        "`error` timeout, network, other status.",
        "",
        "## Sites derived from the code",
        "",
        "| Site | Connector | Bright Data in code | URL tested |",
        "|---|---|---|---|",
    ]
    for r in report["sites"]:
        lines.append(f"| {r['site']} | `{r['connector']}` | {r['bright_data'] or '-'} | {r['url']} |")
    lines += ["", "Referenced but not tested:", ""]
    lines += [f"- {n['site']} ({n['where']}): {n['why']}" for n in report["not_called"]]
    lines += ["", "## Matrix", "",
              "| Site | (a) httpx default UA | (b) httpx browser UA | (c) Bright Data Unlocker "
              "| (d) Bright Data dataset | Marker | Duration a / b / c (s) |",
              "|---|---|---|---|---|---|---|"]
    for r in report["sites"]:
        at = r["attempts"]

        def cell(x: dict[str, Any]) -> str:
            return f"**{x['class']}** ({x['detail']})"

        lines.append(
            f"| {r['site']} | {cell(at['plain_default_ua'])} | {cell(at['plain_browser_ua'])} | "
            f"{cell(at['brightdata_unlocker'])} | {cell(at['brightdata_dataset']) if 'brightdata_dataset' in at else '-'} "
            f"| {r['marker_desc']} | "
            f"{at['plain_default_ua']['duration_s']} / {at['plain_browser_ua']['duration_s']} / "
            f"{at['brightdata_unlocker']['duration_s']} |")
    blocked = [r["site"] for r in report["sites"]
               if not any(r["attempts"][k]["class"] == "ok" for k in ("plain_default_ua", "plain_browser_ua"))]
    lines += ["", "## Not reachable without Bright Data", ""] + [f"- {s}" for s in blocked] + [""]
    return "\n".join(lines)


async def main() -> int:
    key = env_value("BRIGHTDATA_API_KEY")
    client = BrightDataClient(api_key=key, unlocker_zone=ZONE, retries=0) if key else None
    run_at = datetime.now(timezone.utc)
    out_json = ROOT / "data" / "block_matrix.json"
    try:
        if "--datasets-only" in sys.argv:
            report = json.loads(out_json.read_text())
            rows = report["sites"]
            cells = await asyncio.gather(*(dataset_cell(DATASET_SNAPSHOTS.get(r["site"], []), client) for r in rows))
            for r, d in zip(rows, cells, strict=True):
                r["attempts"]["brightdata_dataset"] = d
            report["datasets_read_at"] = run_at.isoformat(timespec="seconds")
            report["counts"] = counts(rows)
        else:
            rows = list(await asyncio.gather(*(probe(s, client) for s in sites())))
            report = {"run_at": run_at.isoformat(timespec="seconds"), "zone": ZONE, "timeout_s": TIMEOUT,
                      "datasets_read_at": run_at.isoformat(timespec="seconds"),
                      "sites": rows, "not_called": NOT_CALLED, "counts": counts(rows)}
    finally:
        if client:
            await client.aclose()
    (ROOT / "data").mkdir(exist_ok=True)
    out_json.write_text(json.dumps(report, indent=1) + "\n")
    (ROOT / "docs" / "BLOCK_MATRIX.md").write_text(markdown(report))
    c = report["counts"]
    print(f"{c['reachable_without_brightdata']} of {c['n']} reachable without Bright Data, "
          f"{c['reachable_with_unlocker_only']} with Web Unlocker alone, "
          f"{c['reachable_with_brightdata']} with Web Unlocker or dataset "
          f"(any path {c['reachable_any_path']}; {c['reachable_with_brightdata_if_kyc_approved']} if KYC approved)")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
