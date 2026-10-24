"""LinkedIn URL discovery for speakers without one: Bright Data SERP, then one dataset batch.

Method after brightdata/pepolehub (read, not copied: no licence) and the field names of
brightdata/linkedin-scraper (Apache-2.0):

1. one Google query per person, ``site:linkedin.com/in <name> <company>``, through the SERP
   zone (``POST /request``, ``google.com/search?q=...&brd_json=1&gl=us``); only the JSON
   ``organic`` is read, never HTML. Bright Data's own keys (seen 2026-10-24): ``title``,
   ``link``, ``description`` (the snippet) and ``rank`` / ``global_rank`` (the position);
   ``snippet`` / ``position`` are read too. Links that are ``google.com/goto?url=<opaque>``
   carry no readable URL and are skipped. 20 s per request; at most 2 retries, network
   errors after ``250*n + rand(220)`` ms, 429/5xx or a non-JSON answer after
   ``320*n**2 + rand(260)`` ms;
2. a free summary from the hit: name and headline from the title (split on " - ", strip
   "| LinkedIn"), location from the snippet;
3. a URL is kept only when the summary name matches the person (initials ignored), the
   company or the person's title corroborates it, the score clears ``THRESHOLD`` (0.7,
   unchanged) and beats the runner-up (a tie is broken only when the person's title
   corroborates one hit and not the other); otherwise none. A URL is never built from a name;
4. the URL is canonical (utm_*, gclid, fbclid and fragment stripped) and carries
   ``brightdata:serp`` provenance;
5. found URLs go to one ``POST /datasets/v3/trigger`` (up to 50 inputs), polled every 2 s
   on ``/snapshot/<id>?format=json``; a row with ``warning_code`` is a private profile (none).

Run from ``scripts/probes/serp_linkedin.py`` only, never at demo startup. Writes: the
Person's ``linkedin_url`` with SERP evidence, then identity_confidence / WORKS_AT
corroboration through ``people_linkedin.write``. No ATTENDS edge, no presence change.
"""

from __future__ import annotations

import asyncio
import json
import random
import re
import time
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import httpx

from conferge.core.schemas import Person
from conferge.integration import people_linkedin as li

PROVIDER = "brightdata:serp"
SERP_ZONE = "serp_api1"
SERP_TIMEOUT_S = 20.0
SERP_RETRIES = 2
MAX_TARGETS = 30
MAX_BATCH = 50
POLL_EVERY_S = 2.0
POLL_TIMEOUT_S = 600.0
_DROP_PARAMS = re.compile(r"^(utm_.*|gclid|fbclid)$", re.I)

Sleep = Callable[[float], Awaitable[Any]]


@dataclass
class Discovery:
    """One person's SERP lookup: what Google returned through Bright Data, and the verdict."""

    person_id: str
    name: str
    company: str | None
    title: str | None
    query: str
    status: str = "failed"  # found / not_found / failed
    linkedin_url: str | None = None
    score: float | None = None
    position: int | None = None
    serp_name: str | None = None
    serp_headline: str | None = None
    serp_location: str | None = None
    reasons: list[str] = field(default_factory=list)
    hits: int = 0
    error: str | None = None
    collected_at: str | None = None


# -- targets and query --------------------------------------------------------------------

def targets_without_url(people: Iterable[Person], cap: int = MAX_TARGETS) -> list[Person]:
    """Announced speakers with no linkedin_url, in data order, at most ``cap``."""
    return [p for p in people
            if p.participation == "confirmed_speaker" and not p.linkedin_url][:cap]


def query_for(name: str, company: str | None) -> str:
    return " ".join(x for x in ("site:linkedin.com/in", name.strip(), (company or "").strip()) if x)


def search_url(query: str) -> str:
    return "https://www.google.com/search?" + urlencode({"q": query, "brd_json": 1, "gl": "us"})


# -- SERP call ----------------------------------------------------------------------------

def backoff_ms(attempt: int, *, status_retry: bool,
               rand: Callable[[int, int], int] = random.randint) -> int:
    """Delay before retry ``attempt`` (1-based): network ``250n + rand(220)``,
    429/5xx ``320n^2 + rand(260)`` milliseconds."""
    if status_retry:
        return 320 * attempt * attempt + rand(0, 260)
    return 250 * attempt + rand(0, 220)


async def serp_organic(query: str, *, http: httpx.AsyncClient, api_key: str,
                       zone: str = SERP_ZONE, sleep: Sleep = asyncio.sleep,
                       rand: Callable[[int, int], int] = random.randint) -> list[dict[str, Any]]:
    """``organic`` of one Google page, as JSON. Raises RuntimeError with a short reason."""
    body = {"zone": zone, "url": search_url(query), "format": "raw"}
    headers = {"Authorization": f"Bearer {api_key}"}
    for attempt in range(SERP_RETRIES + 1):
        try:
            response = await http.post("/request", json=body, headers=headers,
                                       timeout=SERP_TIMEOUT_S)
        except (httpx.TimeoutException, httpx.RequestError) as exc:
            if attempt == SERP_RETRIES:
                raise RuntimeError(f"SERP network error: {type(exc).__name__}") from exc
            await sleep(backoff_ms(attempt + 1, status_retry=False, rand=rand) / 1000)
            continue
        if response.status_code == 429 or response.status_code >= 500:
            if attempt == SERP_RETRIES:
                raise RuntimeError(f"SERP HTTP {response.status_code}")
            await sleep(backoff_ms(attempt + 1, status_retry=True, rand=rand) / 1000)
            continue
        if response.status_code >= 400:
            raise RuntimeError(f"SERP HTTP {response.status_code}")
        try:
            data = response.json()
        except ValueError as exc:  # seen transiently with brd_json=1: retried like a 5xx
            if attempt == SERP_RETRIES:
                raise RuntimeError("SERP answer is not JSON (brd_json=1 expected)") from exc
            await sleep(backoff_ms(attempt + 1, status_retry=True, rand=rand) / 1000)
            continue
        from conferge.core.brightdata import record_call, record_usage

        record_usage("serp")
        record_call("serp", rows=1, status="ready")
        organic = data.get("organic") if isinstance(data, dict) else None
        return [h for h in organic or [] if isinstance(h, dict)]
    raise RuntimeError("SERP retries exhausted")


# -- summary, URL, verdict ----------------------------------------------------------------

def canonical_url(url: str | None) -> str | None:
    """Tracking parameters and fragment stripped, then ``https://www.linkedin.com/in/<slug>/``
    (slug lowercased); None when it is not a profile URL."""
    if not url:
        return None
    parsed = urlparse(url.strip())
    query = urlencode([(k, v) for k, v in parse_qsl(parsed.query) if not _DROP_PARAMS.match(k)])
    return li._canon(urlunparse(parsed._replace(query=query, fragment="")))


def snippet_of(hit: dict[str, Any]) -> str:
    return str(hit.get("description") or hit.get("snippet") or "")


def position_of(hit: dict[str, Any]) -> int | None:
    for key in ("rank", "global_rank", "position"):
        if isinstance(hit.get(key), int):
            return hit[key]
    return None


def summary(hit: dict[str, Any]) -> dict[str, str | None]:
    """Free summary from a SERP hit: name and headline from the title, location from the snippet."""
    title = re.sub(r"\s*\|\s*LinkedIn\s*$", "", str(hit.get("title") or "")).strip()
    parts = [p.strip() for p in title.split(" - ")]
    snippet = snippet_of(hit)
    location = None
    if m := re.search(r"Location:\s*([^·\n]+)", snippet, re.I):
        location = m.group(1).strip()
    elif " · " in snippet:
        tail = snippet.split(" · ")[-1].strip()
        location = tail if tail and len(tail) <= 80 else None
    return {"name": parts[0] or None, "headline": " - ".join(parts[1:]) or None,
            "location": location}


_TITLE_STOP = {"and", "the", "for", "of", "at", "in", "sr", "jr", "senior"}


def title_corroborates(text: str, title: str | None) -> bool:
    """At least 2/3 of the person's significant title words (and at least 2) are in ``text``."""
    from conferge.people.taxonomy import fold

    words = {w for w in re.findall(r"[a-z0-9]+", fold(title or "")) if len(w) > 2} - _TITLE_STOP
    if len(words) < 2:
        return False
    seen = set(re.findall(r"[a-z0-9]+", fold(text)))
    return len(words & seen) >= max(2, -(-2 * len(words) // 3))


def judge(person: Person, company: str | None, hits: list[dict[str, Any]]) -> Discovery:
    """The best LinkedIn hit if name, corroboration, threshold and margin all hold."""
    from conferge.people.linkedin import AMBIGUITY_MARGIN, THRESHOLD, score_candidate

    out = Discovery(person_id=person.id, name=person.name, company=company, title=person.title,
                    query=query_for(person.name, company), hits=len(hits),
                    collected_at=datetime.now(timezone.utc).isoformat())
    ranked = []
    for i, hit in enumerate(hits):
        url = canonical_url(hit.get("link"))
        if not url:
            continue
        cand = score_candidate(person.name, company,
                               {"url": url, "title": hit.get("title"), "snippet": snippet_of(hit)})
        reasons, score = list(cand.reasons), cand.score
        by_company = any(r.startswith("+0.3 company") for r in reasons)
        by_title = title_corroborates(f"{hit.get('title') or ''} {snippet_of(hit)}", person.title)
        if by_title and not by_company:  # the title corroborates like the company, not on top
            score = round(min(score + 0.3, 1.0), 4)
            reasons.append("+0.3 person's title in title or snippet")
        if any(r[2] == url for r in ranked):  # the same profile twice (another Google host)
            continue
        ranked.append((score, i, url, hit, reasons, by_company or by_title, by_title))
    ranked.sort(key=lambda r: (-r[0], not r[6], r[1]))
    if not ranked:
        out.status, out.reasons = "not_found", ["no linkedin.com/in result"]
        return out
    score, _, url, hit, reasons, corroborated, by_title = ranked[0]
    s = summary(hit)
    out.score, out.position, out.reasons = score, position_of(hit), reasons
    out.serp_name, out.serp_headline, out.serp_location = s["name"], s["headline"], s["location"]
    runner_up = ranked[1][0] if len(ranked) > 1 else 0.0
    if len(ranked) > 1 and by_title and not ranked[1][6]:
        runner_up = -1.0  # tie broken: only the best hit carries the person's title
        out.reasons = reasons = [*reasons, "tie broken: the person's title is on this hit only"]
    problem = (
        "name in the SERP title does not match" if not li.name_matches(person.name, s["name"])
        else "neither company nor title corroborates" if not corroborated
        else f"score {score} below {THRESHOLD}" if score < THRESHOLD
        else f"ambiguous: {score} vs {runner_up}" if score - runner_up < AMBIGUITY_MARGIN - 1e-9
        else None)
    if problem:
        out.status, out.reasons = "not_found", [*reasons, problem]
        return out
    out.status, out.linkedin_url = "found", url
    return out


async def discover(people: list[Person], company_names: dict[str, str], *, api_key: str,
                   http: httpx.AsyncClient | None = None, zone: str = SERP_ZONE,
                   sleep: Sleep = asyncio.sleep) -> list[Discovery]:
    """One SERP query per person, sequential (no burst)."""
    own = http is None
    http = http or httpx.AsyncClient(base_url="https://api.brightdata.com")
    out: list[Discovery] = []
    try:
        for person in people:
            company = company_names.get(person.company_id or "")
            try:
                hits = await serp_organic(query_for(person.name, company), http=http,
                                          api_key=api_key, zone=zone, sleep=sleep)
                out.append(judge(person, company, hits))
            except RuntimeError as exc:
                out.append(Discovery(person_id=person.id, name=person.name, company=company,
                                     title=person.title, query=query_for(person.name, company),
                                     error=str(exc),
                                     collected_at=datetime.now(timezone.utc).isoformat()))
    finally:
        if own:
            await http.aclose()
    return out


# -- dataset batch ------------------------------------------------------------------------

async def collect_batch(urls: list[str], *, api_key: str, http: httpx.AsyncClient | None = None,
                        sleep: Sleep = asyncio.sleep,
                        timeout_s: float = POLL_TIMEOUT_S) -> li.Collection:
    """One ``/datasets/v3/trigger`` with up to 50 URLs, then the snapshot every 2 s."""
    from conferge.core.brightdata import BrightDataClient, BrightDataError

    out = li.Collection(status="failed", collected_at=datetime.now(timezone.utc),
                        inputs=list(urls[:MAX_BATCH]), kind="snapshot")
    if not out.inputs:
        out.errors.append("no URL to collect")
        return out
    own = http is None
    http = http or httpx.AsyncClient(base_url="https://api.brightdata.com", timeout=60.0)
    client = BrightDataClient(api_key, client=http)
    try:
        out.snapshot_id = await client.trigger_dataset(
            li.DATASET_ID, [{"url": u} for u in out.inputs], limit_per_input=None)
        deadline = time.monotonic() + timeout_s
        while True:
            res = await client.snapshot_results(out.snapshot_id)
            if res.status != "running":
                out.records = li._rows(res.data)
                break
            if time.monotonic() >= deadline:
                out.errors.append(f"snapshot {out.snapshot_id} not ready after {timeout_s:.0f}s")
                break
            await sleep(POLL_EVERY_S)
    except BrightDataError as exc:
        out.errors.append(str(exc)[:200])
    finally:
        if own:
            await http.aclose()
    private = [r for r in out.records if r.get("warning_code") or r.get("warning")]
    out.errors += [f"private profile ({r.get('warning_code') or 'warning'})" for r in private]
    good = [r for r in out.records if not r.get("error") and r not in private]
    out.status = "ok" if good and not out.errors else "degraded" if good else "failed"
    return out


# -- writes -------------------------------------------------------------------------------

def write_urls(store: Any, found: Iterable[Discovery]) -> list[str]:
    """Person.linkedin_url with SERP evidence, through GraphStore MERGE only."""
    written = []
    for d in found:
        if d.status != "found" or not d.linkedin_url:
            continue
        store.merge_node("Person", d.person_id, li._clean({
            "linkedin_url": d.linkedin_url, "linkedin_url_provider": PROVIDER,
            "serp_query": d.query, "serp_position": d.position, "serp_score": d.score,
            "serp_headline": d.serp_headline, "serp_collected_at": d.collected_at}))
        written.append(d.person_id)
    return written


def apply_urls(people: list[Person], found: Iterable[Discovery]) -> list[Person]:
    """In-memory copy with the discovered linkedin_url (only that field changes)."""
    urls = {d.person_id: d.linkedin_url for d in found if d.status == "found" and d.linkedin_url}
    return [p.model_copy(update={"linkedin_url": urls[p.id]}) if p.id in urls else p
            for p in people]


def save(discoveries: list[Discovery], directory: Path = li.PROBE_DIR) -> Path:
    """Every lookup as returned, ``data/probes/linkedin_serp_<ts>.json`` (never committed)."""
    directory.mkdir(parents=True, exist_ok=True)
    at = datetime.now(timezone.utc)
    path = directory / f"linkedin_serp_{at.strftime('%Y%m%dT%H%M%SZ')}.json"
    path.write_text(json.dumps({"provider": PROVIDER, "zone": SERP_ZONE, "at": at.isoformat(),
                                "discoveries": [asdict(d) for d in discoveries]},
                               indent=1, ensure_ascii=False), encoding="utf-8")
    return path
