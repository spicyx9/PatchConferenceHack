"""Bright Data SERP discovery source (window 04).

`SerpDiscoverySource.discover` turns a conference-aware query plan into Google
SERP calls through the shared `BrightDataClient.serp` (no new API client), with
bounded concurrency and duplicate URL suppression. Each unique URL becomes a
`SourceRecord` of kind `discovery_candidate`: a URL worth verifying, never a
confirmed event. `fetch_details` routes the URL to the owning adapter.
"""

from __future__ import annotations

import asyncio
import hashlib
import importlib
import json
import re
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Any

import httpx

from conferge.core.brightdata import BrightDataClient, BrightDataError
from conferge.core.schemas import (
    DiscoveryQuery,
    DiscoveryResult,
    RunReport,
    RunStatus,
    SourceMode,
    SourceRecord,
    SourceRef,
    Termination,
)
from conferge.events.discovery.jsonld import extract_event_jsonld, payload_hash
from conferge.events.discovery.queries import QueryPlan, SerpQuery, build_queries
from conferge.events.discovery.router import Route, route_url

PROVIDER = "brightdata_serp"
JSONLD_PROVIDER = "web_jsonld"
RECORD_KIND = "discovery_candidate"
_KIND_BASE = {
    "event_page": 0.5, "event_or_calendar": 0.4, "other": 0.2, "listing": 0.15,
    "profile": 0.1, "post": 0.1,
}
_BLOCK_MARKERS = ("unusual traffic", "/sorry/index", "detected unusual", "captcha")
_BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"
)

SerpFn = Callable[[str], Awaitable[str]]


class DiscoveryError(RuntimeError):
    """Visible discovery failure; messages never contain credentials or bodies."""


class SerpBlocked(DiscoveryError):
    pass


# --------------------------------------------------------------------- parsing
class _GoogleHtmlParser(HTMLParser):
    """Collect organic results: anchors that wrap an <h3> title."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.hits: list[dict[str, Any]] = []
        self._href: str | None = None
        self._in_h3 = False
        self._title: list[str] = []
        self._anchor_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "a":
            href = dict(attrs).get("href")
            if href:
                self._href = href
                self._anchor_depth = 1
                self._title = []
        elif tag == "h3" and self._href:
            self._in_h3 = True

    def handle_data(self, data: str) -> None:
        if self._in_h3:
            self._title.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "h3" and self._in_h3:
            self._in_h3 = False
            title = " ".join("".join(self._title).split())
            if self._href and title:
                self.hits.append({"url": self._href, "title": title, "snippet": None})
        elif tag == "a" and self._anchor_depth:
            self._href = None
            self._anchor_depth = 0


def parse_serp(body: str) -> list[dict[str, Any]]:
    """Organic hits `{url, title, snippet, position}` from Bright Data SERP output.

    Accepts the parsed JSON shape (`brd_json=1`, key `organic`) or raw Google HTML.
    Raises `SerpBlocked` on a CAPTCHA / unusual traffic page.
    """
    text = body.strip()
    hits: list[dict[str, Any]] = []
    if text.startswith("{"):
        try:
            data = json.loads(text)
        except ValueError:
            data = None
        if isinstance(data, dict):
            for item in data.get("organic") or []:
                if not isinstance(item, dict):
                    continue
                url = item.get("link") or item.get("url")
                if isinstance(url, str):
                    hits.append({
                        "url": url,
                        "title": item.get("title") if isinstance(item.get("title"), str) else None,
                        "snippet": next((item[k] for k in ("description", "snippet")
                                         if isinstance(item.get(k), str)), None),
                        "position": item.get("rank") if isinstance(item.get("rank"), int) else None,
                    })
            for pos, hit in enumerate(hits, start=1):
                hit["position"] = hit["position"] or pos
            return hits
    lowered = text[:20000].casefold()
    if any(marker in lowered for marker in _BLOCK_MARKERS) and "<h3" not in lowered:
        raise SerpBlocked("SERP returned a CAPTCHA / unusual traffic page")
    parser = _GoogleHtmlParser()
    try:
        parser.feed(text)
    except Exception:  # noqa: BLE001 - malformed HTML is reported as zero hits
        return []
    for pos, hit in enumerate(parser.hits, start=1):
        hit["position"] = pos
        hits.append(hit)
    return hits


# ---------------------------------------------------------------------- helpers
def _source_id(canonical_url: str) -> str:
    return "serp:" + hashlib.sha1(canonical_url.encode()).hexdigest()[:16]


def plan_from_query(query: DiscoveryQuery) -> QueryPlan:
    """Build a QueryPlan from a DiscoveryQuery; conference details travel in `filters`."""
    if not query.city:
        raise ValueError("DiscoveryQuery.city is required for SERP discovery")
    f = query.filters

    def strings(key: str) -> list[str]:
        value = f.get(key) or []
        return [str(v) for v in value if isinstance(v, str) and v.strip()]

    return QueryPlan(
        city=query.city,
        conference_name=f.get("conference_name") if isinstance(f.get("conference_name"), str)
        else None,
        aliases=strings("aliases"),
        venue=f.get("venue") if isinstance(f.get("venue"), str) else None,
        start_date=query.start_date,
        end_date=query.end_date,
        sponsors=strings("sponsors"),
        hosts=strings("hosts"),
        topics=strings("topics") or list(query.keywords),
    )


def candidate_confidence(route: Route, hits: list[dict[str, Any]],
                         conference_terms: list[str]) -> float:
    """Heuristic relevance of a candidate URL, capped at 0.8: not a confirmation."""
    score = _KIND_BASE.get(route.page_kind, 0.1)
    if route.adapter == "none":
        score -= 0.05
    if len({h["query"] for h in hits}) > 1:
        score += 0.1
    if any(h.get("family") in {"conference", "host"} for h in hits):
        score += 0.1
    blob = " ".join(f"{h.get('title') or ''} {h.get('snippet') or ''}" for h in hits).casefold()
    if any(term.casefold() in blob for term in conference_terms if term):
        score += 0.15
    return round(max(0.0, min(score, 0.8)), 3)


# ----------------------------------------------------------------------- source
class SerpDiscoverySource:
    """`conferge.core.contracts.Source` for long-tail SERP discovery."""

    provider = PROVIDER

    def __init__(
        self,
        brightdata: BrightDataClient | None = None,
        *,
        serp: SerpFn | None = None,
        source_mode: SourceMode = "live",
        concurrency: int = 4,
        max_queries: int = 40,
        country: str = "us",
        http: httpx.AsyncClient | None = None,
    ) -> None:
        self._bd = brightdata
        self._serp_override = serp
        self.source_mode = source_mode
        self.concurrency = max(1, concurrency)
        self.max_queries = max_queries
        self.country = country
        self._http = http

    # ---------------------------------------------------------------- transport
    def _serp_ready(self) -> str | None:
        if self._serp_override is not None:
            return None
        if self._bd is None:
            return "Bright Data client not configured"
        if not getattr(self._bd, "_api_key", None):
            return "Bright Data key missing; set BRIGHTDATA_API_KEY"
        if not self._bd.serp_zone:
            return "BRIGHTDATA_SERP_ZONE not configured"
        return None

    async def _call_serp(self, text: str) -> str:
        if self._serp_override is not None:
            return await self._serp_override(text)
        assert self._bd is not None
        return await self._bd.serp(text, country=self.country)

    # ---------------------------------------------------------------- discover
    async def discover(self, query: DiscoveryQuery) -> DiscoveryResult:
        started = datetime.now(timezone.utc)
        try:
            plan = plan_from_query(query)
        except ValueError as exc:
            return self._result([], started, "failed", "error", errors=[str(exc)])
        return await self.discover_plan(plan, limit=query.limit, started=started)

    async def discover_plan(
        self, plan: QueryPlan, *, limit: int = 1000, started: datetime | None = None,
    ) -> DiscoveryResult:
        started = started or datetime.now(timezone.utc)
        not_ready = self._serp_ready()
        if not_ready:
            return self._result([], started, "failed", "error", errors=[not_ready])
        queries = build_queries(plan)
        warnings: list[str] = []
        if len(queries) > self.max_queries:
            warnings.append(f"query plan capped at {self.max_queries} of {len(queries)} queries")
            queries = queries[: self.max_queries]
        sem = asyncio.Semaphore(self.concurrency)

        async def one(q: SerpQuery) -> tuple[SerpQuery, list[dict[str, Any]] | None, str | None]:
            async with sem:
                try:
                    return q, parse_serp(await self._call_serp(q.text)), None
                except SerpBlocked as exc:
                    return q, None, f"blocked: {q.text!r}: {exc}"
                except BrightDataError as exc:
                    return q, None, f"serp error: {q.text!r}: {exc}"
                except (httpx.HTTPError, ValueError, KeyError) as exc:
                    return q, None, f"serp error: {q.text!r}: {exc.__class__.__name__}"

        outcomes = await asyncio.gather(*(one(q) for q in queries))
        collected_at = datetime.now(timezone.utc)
        errors = [err for _, _, err in outcomes if err]
        by_url: dict[str, tuple[Route, list[dict[str, Any]]]] = {}
        fetched = 0
        skipped_search = 0
        for q, hits, _ in outcomes:
            for hit in hits or []:
                fetched += 1
                try:
                    route = route_url(hit["url"])
                except ValueError:
                    continue
                if route.platform == "search_engine":
                    skipped_search += 1
                    continue
                entry = by_url.setdefault(route.canonical_url, (route, []))
                entry[1].append({
                    "query": q.text, "family": q.family, "reason": q.reason,
                    "position": hit.get("position"), "title": hit.get("title"),
                    "snippet": hit.get("snippet"),
                })
        if skipped_search:
            warnings.append(f"ignored {skipped_search} search-engine internal links")
        terms = [t for t in [plan.conference_name, *plan.aliases] if t]
        items: list[SourceRecord] = []
        for canonical, (route, hits) in by_url.items():
            payload = {
                "record_kind": RECORD_KIND,
                "verified_event": False,
                "url": route.url,
                "canonical_url": canonical,
                "route": route.model_dump(),
                "discovered_by": hits,
                "confidence": candidate_confidence(route, hits, terms),
                "note": "SERP candidate URL; not a confirmed event or conference relation",
            }
            items.append(SourceRecord(
                provider=PROVIDER, source_id=_source_id(canonical), source_mode=self.source_mode,
                collected_at=collected_at, payload=payload, source_url=canonical,
                content_hash=payload_hash(payload),
            ))
        items.sort(key=lambda r: (-r.payload["confidence"], r.payload["canonical_url"]))
        truncated = len(items) > limit
        if truncated:
            warnings.append(f"candidates truncated to limit={limit} of {len(items)}")
            items = items[:limit]

        ok_queries = sum(1 for _, hits, _ in outcomes if hits is not None)
        status: RunStatus
        termination: Termination
        if ok_queries == 0:
            status = "failed"
            termination = "blocked" if all(e.startswith("blocked") for e in errors) else "error"
        elif errors:
            status, termination = "degraded", "error"
        elif not items:
            status, termination = "degraded", "schema_changed"
            warnings.append("zero organic results across all queries (parser or SERP drift?)")
        elif truncated:
            status, termination = "degraded", "page_cap"
        else:
            status, termination = "ok", "not_applicable"
            warnings.append("SERP is top-N per query by design; no completeness claim")
        return self._result(items, started, status, termination, fetched=fetched,
                            pages=ok_queries, errors=errors, warnings=warnings)

    def _result(
        self, items: list[SourceRecord], started: datetime, status: RunStatus,
        termination: Termination, *, fetched: int = 0, pages: int = 0,
        errors: list[str] | None = None, warnings: list[str] | None = None,
    ) -> DiscoveryResult:
        report = RunReport(
            provider=PROVIDER, started_at=started, finished_at=datetime.now(timezone.utc),
            status=status, termination=termination, source_mode=self.source_mode,
            fetched_count=max(fetched, len(items)), unique_count=len(items), pages=pages,
            errors=list(errors or []), warnings=list(warnings or []),
        )
        return DiscoveryResult(items=items, run_report=report, errors=list(errors or []))

    # ------------------------------------------------------------- fetch_details
    async def fetch_details(self, ref: SourceRef) -> SourceRecord:
        """Verify a candidate by routing it to its platform adapter.

        Raises `DiscoveryError` when no adapter can verify the URL; the candidate
        then stays unverified (never promoted to an Event from its snippet).
        """
        if ref.url is None:
            raise DiscoveryError("fetch_details needs a candidate URL")
        route = route_url(str(ref.url))
        url = route.canonical_url
        if route.adapter == "luma":
            src = self._adapter("conferge.events.luma", "LumaSource", brightdata=self._bd)
            if src is not None:
                return await self._closing(src, SourceRef(provider="luma",
                                                          source_id=route.platform_id or url,
                                                          url=url))
        elif route.adapter == "partiful":
            src = self._adapter("conferge.events.partiful", "PartifulSource", brightdata=self._bd)
            if src is not None:
                return await self._closing(src, SourceRef(provider="partiful",
                                                          source_id=route.platform_id or url,
                                                          url=url))
        elif route.adapter == "eventbrite":
            src = self._adapter("conferge.events.eventbrite", "EventbriteSource")
            if src is not None:
                return await self._closing(src, SourceRef(provider="eventbrite",
                                                          source_id=route.platform_id or url,
                                                          url=url))
        elif route.adapter == "facebook_events":
            from conferge.events.discovery.facebook import FacebookEventsSource

            return await FacebookEventsSource(self._bd).fetch_details(
                SourceRef(provider="facebook_events", source_id=route.platform_id or url, url=url)
            )
        elif route.adapter != "jsonld":
            raise DiscoveryError(
                f"no detail adapter for {route.platform}/{route.page_kind}; candidate kept "
                "unverified"
            )
        return await self.fetch_jsonld(url, route)

    @staticmethod
    def _adapter(module: str, cls: str, **kwargs: Any) -> Any:
        """Dynamic import so discovery keeps working if a sibling window is absent."""
        try:
            return getattr(importlib.import_module(module), cls)(**kwargs)
        except (ImportError, AttributeError):
            return None

    @staticmethod
    async def _closing(src: Any, ref: SourceRef) -> SourceRecord:
        try:
            return await src.fetch_details(ref)
        except DiscoveryError:
            raise
        except Exception as exc:  # noqa: BLE001 - sibling adapters raise their own types
            raise DiscoveryError(f"{ref.provider} detail fetch failed: {exc}") from exc
        finally:
            close = getattr(src, "aclose", None)
            if close is not None:
                await close()

    async def _get_page(self, url: str, warnings: list[str]) -> tuple[str, str]:
        bd = self._bd
        if bd is not None and bd.unlocker_zone and getattr(bd, "_api_key", None):
            try:
                return await bd.unlock(url), "web_unlocker"
            except BrightDataError as exc:
                warnings.append(f"Web Unlocker failed ({exc}); trying direct public GET")
        else:
            warnings.append("Web Unlocker not configured; direct public GET")
        client = self._http or httpx.AsyncClient(
            timeout=20.0, follow_redirects=True, headers={"User-Agent": _BROWSER_UA}
        )
        try:
            response = await client.get(url)
        except httpx.HTTPError as exc:
            raise DiscoveryError(f"page fetch network error: {exc.__class__.__name__}") from exc
        finally:
            if self._http is None:
                await client.aclose()
        if response.status_code >= 400:
            raise DiscoveryError(f"page fetch HTTP {response.status_code}")
        return response.text, "direct_get"

    async def fetch_jsonld(self, url: str, route: Route | None = None) -> SourceRecord:
        """Independent page: keep schema.org Event JSON-LD blocks, else raise."""
        warnings: list[str] = []
        html, method = await self._get_page(url, warnings)
        collected_at = datetime.now(timezone.utc)
        events = extract_event_jsonld(html)
        if not events:
            raise DiscoveryError(
                "no schema.org Event JSON-LD on page; LLM extraction unavailable (no key), "
                "candidate kept unverified"
            )
        payload = {
            "jsonld_events": events[:5],
            "fetch_method": method,
            "route": (route or route_url(url)).model_dump(),
            "detail_warnings": warnings,
        }
        title = re.sub(r"\s+", " ", str(events[0].get("name") or ""))[:80]
        return SourceRecord(
            provider=JSONLD_PROVIDER, source_id=_source_id(url).replace("serp:", "page:"),
            source_mode="live", collected_at=collected_at, payload=payload, source_url=url,
            request_id=method, content_hash=payload_hash({"events": events, "title": title}),
        )
