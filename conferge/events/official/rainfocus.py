"""Public RainFocus catalog client used by the GitHub Universe 2026 attendee portal.

How the endpoint was found (see probes/official.md):
1. githubuniverse.com links to reg.githubuniverse.com/flow/github/universe26/attendee-portal.
2. That portal is a RainFocus "workflow"; every page is the same JS shell.
3. GET flow/loadPage?pageUri=<page>&workflowApiToken=<workflow> returns the page layout
   with the catalog widget id (data-widgetid on #rf-catalog / #rf-exhibitorcatalog) and a
   public, per-load apiProfileToken in widgetConf.
4. POST https://events.rainfocus.com/api/search (headers rfWidgetId, rfApiProfileId),
   form body type=session|exhibitor&from=<offset>, pages of 50.

Only publicly visible (unauthenticated) catalog data is read. The api profile token is
fetched at runtime, never hard-coded, never logged, never written to errors.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Literal
from urllib.parse import urlencode, urlsplit

import httpx

from conferge.core.brightdata import BrightDataClient, BrightDataError
from conferge.core.schemas import Termination

logger = logging.getLogger(__name__)

PORTAL_BASE = "https://reg.githubuniverse.com/"
WORKFLOW_TOKEN = "github.universe26.attendee-portal"
WORKFLOW_PATH = "flow/github/universe26/attendee-portal"
API_BASE = "https://events.rainfocus.com/"
SESSION_CATALOG_PAGE = "sessioncatalog"
SPONSOR_CATALOG_PAGE = "sponsors"
CATALOG_URL = f"{PORTAL_BASE}{WORKFLOW_PATH}/page/{SESSION_CATALOG_PAGE}"
SPONSOR_URL = f"{PORTAL_BASE}{WORKFLOW_PATH}/page/{SPONSOR_CATALOG_PAGE}"
USER_AGENT = "Mozilla/5.0 (compatible; Conferge/0.1; +https://github.com/spicyx9/HTest)"

Kind = Literal["session", "exhibitor"]
_WIDGET_ELEMENT = {"session": "rf-catalog", "exhibitor": "rf-exhibitorcatalog"}
_PAGE_FOR_KIND = {"session": SESSION_CATALOG_PAGE, "exhibitor": SPONSOR_CATALOG_PAGE}
_ID_FIELD = {"session": "sessionID", "exhibitor": "exhibitorID"}


class RainFocusError(RuntimeError):
    """Sanitized failure with a RunReport termination code."""

    def __init__(self, message: str, termination: Termination = "error") -> None:
        super().__init__(message)
        self.termination: Termination = termination


@dataclass
class WidgetConfig:
    widget_id: str
    api_profile_token: str = field(repr=False)


@dataclass
class SearchRun:
    kind: Kind
    items: list[dict[str, Any]] = field(default_factory=list)
    pages: int = 0
    fetched_count: int = 0
    expected_count: int | None = None
    termination: Termination = "error"
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def complete(self) -> bool:
        return self.termination == "exhausted"


def _termination_for_status(code: int) -> Termination:
    if code == 429:
        return "rate_limited"
    if code in {401, 403}:
        return "blocked"
    return "error"


def extract_widget_id(page_data: Any, kind: Kind) -> str | None:
    """Find the catalog widget id inside a loadPage layout tree."""
    blob = json.dumps(page_data)
    element = _WIDGET_ELEMENT[kind]
    pattern = rf'id=\\"{element}\\"\s+data-widgetid=\\"([A-Za-z0-9]+)\\"'
    match = re.search(pattern, blob)
    return match.group(1) if match else None


def extract_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """First page nests items in sectionList; later pages put them at the top level."""
    if isinstance(payload.get("sectionList"), list):
        out: list[dict[str, Any]] = []
        for section in payload["sectionList"]:
            out.extend(section.get("items") or [])
        return out
    return list(payload.get("items") or [])


def extract_total(payload: dict[str, Any]) -> int | None:
    for key in ("totalSearchItems", "total"):
        if isinstance(payload.get(key), int):
            return payload[key]
    sections = payload.get("sectionList")
    if isinstance(sections, list) and sections and isinstance(sections[0].get("total"), int):
        return sections[0]["total"]
    return None


class RainFocusClient:
    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        *,
        portal_base: str = PORTAL_BASE,
        api_base: str = API_BASE,
        workflow_token: str = WORKFLOW_TOKEN,
        page_size: int = 50,
        max_pages: int = 40,
        delay_s: float = 0.3,
        brightdata: BrightDataClient | None = None,
    ) -> None:
        self._client = client or httpx.AsyncClient(
            timeout=30.0, headers={"User-Agent": USER_AGENT}, follow_redirects=True
        )
        self._owns_client = client is None
        # githubuniverse.com pages go through Bright Data Web Unlocker when key + zone are set;
        # direct GET otherwise or on any Unlocker error. The api/search POST (custom widget
        # headers) stays direct: Unlocker POST with those headers is not verified.
        self._bd = brightdata
        self.transport: dict[str, int] = {"brightdata:web_unlocker": 0, "direct": 0}
        self._notes: list[str] = []
        self.portal_base = portal_base
        self.api_base = api_base
        self.workflow_token = workflow_token
        self.page_size = page_size
        self.max_pages = max_pages
        self.delay_s = delay_s

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()
        if self._bd is not None:
            await self._bd.aclose()

    def drain_notes(self) -> list[str]:
        notes, self._notes = list(dict.fromkeys(self._notes)), []
        return notes

    async def _unlocked_json(self, url: str, params: dict[str, Any] | None) -> dict[str, Any] | None:
        """Portal GET through Web Unlocker; None means "use the direct GET" (reason noted)."""
        if self._bd is None or not (urlsplit(url).hostname or "").endswith("githubuniverse.com"):
            return None
        reason = self._bd.not_ready("web_unlocker")
        if reason:
            self._notes.append(f"{reason}: direct GET for githubuniverse.com")
            return None
        full = url + ("?" + urlencode(params) if params else "")
        try:
            data = json.loads(await self._bd.unlock(full))
        except (BrightDataError, ValueError) as exc:
            self._notes.append(f"Web Unlocker failed ({exc}); direct GET fallback")
            return None
        if not isinstance(data, dict):
            self._notes.append("Web Unlocker returned non-object JSON; direct GET fallback")
            return None
        self.transport["brightdata:web_unlocker"] += 1
        return data

    async def __aenter__(self) -> RainFocusClient:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    async def _json(self, method: str, url: str, **kwargs: Any) -> dict[str, Any]:
        if method == "GET":
            unlocked = await self._unlocked_json(url, kwargs.get("params"))
            if unlocked is not None:
                return unlocked
        self.transport["direct"] += 1
        try:
            response = await self._client.request(method, url, **kwargs)
        except (httpx.RequestError, httpx.TimeoutException) as exc:
            raise RainFocusError(f"RainFocus {method} {url}: network error") from exc
        if response.status_code >= 400:
            raise RainFocusError(
                f"RainFocus {method} {url}: HTTP {response.status_code}",
                _termination_for_status(response.status_code),
            )
        try:
            data = response.json()
        except ValueError as exc:
            raise RainFocusError(
                f"RainFocus {method} {url}: non-JSON response", "schema_changed"
            ) from exc
        if not isinstance(data, dict):
            raise RainFocusError(f"RainFocus {url}: unexpected JSON shape", "schema_changed")
        return data

    async def widget_config(self, kind: Kind) -> WidgetConfig:
        page = _PAGE_FOR_KIND[kind]
        data = await self._json(
            "GET",
            f"{self.portal_base}flow/loadPage",
            params={"pageUri": page, "workflowApiToken": self.workflow_token},
        )
        body = data.get("data") if isinstance(data.get("data"), dict) else {}
        if body.get("responseCode") != "0":
            raise RainFocusError(f"RainFocus loadPage {page}: responseCode {body.get('responseCode')}",
                                 "schema_changed")
        widget_id = extract_widget_id(body.get("pageData"), kind)
        token = (body.get("widgetConf") or {}).get("apiProfileToken")
        if not widget_id or not token:
            raise RainFocusError(f"RainFocus loadPage {page}: catalog widget not found",
                                 "schema_changed")
        return WidgetConfig(widget_id=widget_id, api_profile_token=str(token))

    async def search(self, kind: Kind, *, limit: int | None = None) -> SearchRun:
        """Drain a catalog. Never raises; failures are reported in SearchRun."""
        run = SearchRun(kind=kind)
        try:
            config = await self.widget_config(kind)
        except RainFocusError as exc:
            run.termination = exc.termination
            run.errors.append(str(exc))
            run.warnings.extend(self.drain_notes())
            return run
        run.warnings.extend(self.drain_notes())
        headers = {
            "rfWidgetId": config.widget_id,
            "rfApiProfileId": config.api_profile_token,
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Origin": self.portal_base.rstrip("/"),
            "Referer": self.portal_base,
        }
        seen: set[str] = set()
        offset = 0
        id_field = _ID_FIELD[kind]
        while True:
            if run.pages >= self.max_pages:
                run.termination = "page_cap"
                run.warnings.append(f"{kind}: stopped at page cap {self.max_pages}")
                return run
            try:
                payload = await self._json(
                    "POST", f"{self.api_base}api/search", headers=headers,
                    data={"type": kind, "from": str(offset), "size": str(self.page_size)},
                )
            except RainFocusError as exc:
                run.termination = exc.termination
                run.errors.append(str(exc))
                return run
            run.pages += 1
            if str(payload.get("responseCode")) != "0":
                run.termination = "schema_changed"
                run.errors.append(f"{kind}: responseCode {payload.get('responseCode')}")
                return run
            total = extract_total(payload)
            if total is not None:
                run.expected_count = total
            page_items = extract_items(payload)
            run.fetched_count += len(page_items)
            new = 0
            for item in page_items:
                key = str(item.get(id_field) or "")
                if not key:
                    run.warnings.append(f"{kind}: item without {id_field} skipped")
                    continue
                if key in seen:
                    continue
                seen.add(key)
                run.items.append(item)
                new += 1
                if limit is not None and len(run.items) >= limit:
                    if run.expected_count is not None and run.expected_count <= len(run.items):
                        run.termination = "exhausted"
                    else:
                        run.termination = "page_cap"
                        run.warnings.append(f"{kind}: stopped at query limit {limit}")
                    return run
            logger.info("rainfocus.page", extra={"kind": kind, "offset": offset, "new": new})
            if not page_items:
                if run.expected_count is not None and len(run.items) < run.expected_count:
                    run.termination = "cursor_stuck"
                    run.warnings.append(
                        f"{kind}: empty page at offset {offset} before declared total"
                    )
                else:
                    run.termination = "exhausted"
                return run
            if new == 0:
                run.termination = "cursor_stuck"
                run.warnings.append(f"{kind}: page at offset {offset} repeated known ids")
                return run
            if run.expected_count is not None and len(run.items) >= run.expected_count:
                run.termination = "exhausted"
                return run
            offset += len(page_items)
            if self.delay_s:
                await asyncio.sleep(self.delay_s)
