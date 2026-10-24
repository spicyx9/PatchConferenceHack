"""Single Bright Data HTTP client shared by all source adapters.

No automatic fabrication: fixture fallback is opt-in and visibly labelled.
Secrets are never interpolated into logs or exception messages.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import re
from collections.abc import Awaitable, Callable
from email.utils import parsedate_to_datetime
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlencode

import httpx
from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)
_RETRY_STATUSES = {408, 429, 500, 502, 503, 504}
# Backoff from Bright Data's ticket-hunter-agent browser-utils.ts (attempt n = 1, 2):
# network error 0.25*n + U(0, 0.22) s; HTTP 429/408/5xx 0.32*n^2 + U(0, 0.26) s;
# Retry-After honoured up to 30 s; a Bright Data "cooldown" / "no_peers" answer waits 15 then 30 s.
NETWORK_BACKOFF = (0.25, 0.22)
STATUS_BACKOFF = (0.32, 0.26)
RETRY_AFTER_MAX = 30.0
MAX_RETRIES = 2
# Bright Data out of peers / in cooldown (Unlocker and datasets alike): wait 15, 30, 60 s,
# at most 3 retries, then the source is degraded with the warning NO_PEERS.
COOLDOWN_DELAYS = (15.0, 30.0, 60.0)
_COOLDOWN = re.compile(r"cooldown|no_peers", re.I)
NO_PEERS = "brightdata_no_peers"


def has_no_peers(payload: Any) -> bool:
    """True when a body or a record says no_peers / cooldown (error, error_code, status, text)."""
    if isinstance(payload, str):
        return bool(_COOLDOWN.search(payload[:4000]))
    if isinstance(payload, dict):
        return any(isinstance(payload.get(k), str) and _COOLDOWN.search(payload[k])
                   for k in ("error", "error_code", "status", "message"))
    if isinstance(payload, list):
        return any(has_no_peers(r) for r in payload if isinstance(r, dict))
    return False
# Web Unlocker answered 200 but the page is a bot wall: title + first 4000 chars.
BLOCK_PATTERNS = ("captcha", "verify you are human", "access denied", "unusual traffic",
                  "cf-chl", "challenge-platform")
BLOCK_VENDORS = ("cloudflare", "perimeterx", "incapsula", "recaptcha", "datadome", "akamai")
_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)


def network_delay(attempt: int, rand: Callable[[float, float], float] = random.uniform) -> float:
    return NETWORK_BACKOFF[0] * attempt + rand(0, NETWORK_BACKOFF[1])


def status_delay(attempt: int, rand: Callable[[float, float], float] = random.uniform) -> float:
    return STATUS_BACKOFF[0] * attempt ** 2 + rand(0, STATUS_BACKOFF[1])


def retry_after_seconds(value: str | None, now: datetime | None = None) -> float | None:
    """Retry-After as seconds (delta or HTTP date), capped at RETRY_AFTER_MAX; None if absent."""
    if not value:
        return None
    try:
        seconds = float(value.strip())
    except ValueError:
        try:
            when = parsedate_to_datetime(value)
        except (TypeError, ValueError):
            return None
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        seconds = (when - (now or datetime.now(timezone.utc))).total_seconds()
    return max(0.0, min(seconds, RETRY_AFTER_MAX))


def block_reason(html: str) -> str | None:
    """``unlocker_blocked`` pattern when an unlocked page is a challenge, else None."""
    m = _TITLE.search(html[:20000])
    hay = f"{m.group(1) if m else ''} {html[:4000]}".lower()
    for pattern in BLOCK_PATTERNS:
        if pattern in hay:
            return pattern
    vendors = [v for v in BLOCK_VENDORS if v in hay]
    return "+".join(vendors) if len(vendors) >= 2 else None
# /datasets/v3/scrape holds the connection up to ~60 s before answering 202 + snapshot_id.
SYNC_TIMEOUT = 75.0

BrightDataApi = Literal["datasets", "web_unlocker", "serp"]
# Process-wide count of what Bright Data actually returned (successful responses only):
# dataset rows, Web Unlocker pages, SERP result pages. Shown on the demo home screen.
_USAGE: dict[str, int] = {"datasets": 0, "web_unlocker": 0, "serp": 0}
# Every Bright Data call that got an answer: api, dataset_id, snapshot_id, rows, status, at.
_CALLS: list[dict[str, Any]] = []


def parse_body(response: httpx.Response) -> Any:
    """JSON body, or a list of rows when Bright Data answers JSON Lines (application/jsonl)."""
    ctype = response.headers.get("content-type", "")
    text = response.text
    if "jsonl" in ctype or "ndjson" in ctype:
        return [json.loads(line) for line in text.splitlines() if line.strip()]
    try:
        return json.loads(text) if text.strip() else None
    except json.JSONDecodeError:
        try:
            return [json.loads(line) for line in text.splitlines() if line.strip()]
        except json.JSONDecodeError as exc:
            raise BrightDataError("Bright Data response is neither JSON nor JSON Lines") from exc


def record_usage(api: BrightDataApi, count: int = 1) -> None:
    _USAGE[api] = _USAGE.get(api, 0) + max(count, 0)


def record_call(api: BrightDataApi, *, rows: int, status: str, dataset_id: str | None = None,
                snapshot_id: str | None = None) -> None:
    _CALLS.append({"api": api, "dataset_id": dataset_id, "snapshot_id": snapshot_id,
                   "rows": rows, "status": status,
                   "at": datetime.now(timezone.utc).isoformat()})


def _data_rows(payload: Any) -> int:
    """Rows that are records: Bright Data returns failed inputs as rows with an ``error`` key."""
    rows = payload if isinstance(payload, list) else [payload]
    return sum(1 for r in rows if isinstance(r, dict) and r and "error" not in r)


def calls() -> list[dict[str, Any]]:
    return [dict(c) for c in _CALLS]


def usage() -> dict[str, int]:
    return {**_USAGE, "total": sum(_USAGE.values())}


def reset_usage() -> None:
    for key in _USAGE:
        _USAGE[key] = 0
    _CALLS.clear()


class BrightDataError(RuntimeError):
    """Sanitized error; never contains request credentials or response body."""


class CollectionOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["ready", "running", "fixture"]
    source_mode: Literal["live", "fixture"]
    collected_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    data: Any = None
    snapshot_id: str | None = None
    warnings: list[str] = Field(default_factory=list)


class BrightDataClient:
    def __init__(
        self,
        api_key: str | None,
        *,
        serp_zone: str | None = None,
        unlocker_zone: str | None = None,
        client: httpx.AsyncClient | None = None,
        retries: int = 2,
        sleep: Callable[[float], Awaitable[Any]] | None = None,
        rand: Callable[[float, float], float] | None = None,
    ) -> None:
        self._api_key = api_key
        self._sleep = sleep or asyncio.sleep
        self._rand = rand or random.uniform
        self.serp_zone = serp_zone
        self.unlocker_zone = unlocker_zone
        self._client = client or httpx.AsyncClient(
            base_url="https://api.brightdata.com", timeout=SYNC_TIMEOUT
        )
        self._owns_client = client is None
        self.retries = min(retries, MAX_RETRIES)  # never more than 2 retries

    @classmethod
    def from_env(cls) -> BrightDataClient:
        """Key and zones from the process env, else the repo-root .env (conferge.core.settings)."""
        from conferge.core.settings import env_value

        return cls(
            api_key=env_value("BRIGHTDATA_API_KEY") or None,
            serp_zone=env_value("BRIGHTDATA_SERP_ZONE") or None,
            unlocker_zone=env_value("BRIGHTDATA_UNLOCKER_ZONE") or None,
        )

    def not_ready(self, api: BrightDataApi) -> str | None:
        """Why ``api`` cannot be used right now (callers then take their fallback), or None."""
        if not self._api_key:
            return "Bright Data key missing; set BRIGHTDATA_API_KEY"
        if api == "serp" and not self.serp_zone:
            return "BRIGHTDATA_SERP_ZONE not configured"
        if api == "web_unlocker" and not self.unlocker_zone:
            return "BRIGHTDATA_UNLOCKER_ZONE not configured"
        return None

    async def __aenter__(self) -> BrightDataClient:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    def _status_wait(self, response: httpx.Response, attempt: int) -> float:
        """Delay before retry ``attempt`` (1-based) after a retryable, non-cooldown HTTP status."""
        after = retry_after_seconds(response.headers.get("retry-after"))
        return after if after is not None else status_delay(attempt, self._rand)

    async def _request(
        self, method: str, path: str, *, params: dict[str, Any] | None = None,
        payload: Any = None, timeout: float | None = None, retry_network: bool = True,
    ) -> httpx.Response:
        if not self._api_key:
            raise BrightDataError("Bright Data key missing; set BRIGHTDATA_API_KEY")
        attempt = 0  # ordinary retries (network, 429/408/5xx): at most self.retries
        cooldowns = 0  # no_peers / cooldown answers: their own 15, 30, 60 s budget
        while True:
            try:
                logger.info("brightdata.request", extra={"endpoint": path, "attempt": attempt + 1})
                response = await self._client.request(
                    method, path, params=params, json=payload,
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    **({"timeout": timeout} if timeout is not None else {}),
                )
            except (httpx.RequestError, httpx.TimeoutException) as exc:
                # Ambiguous: the server may have started a billed collection. Never resend
                # when the caller says so (retry_network=False on POST /scrape).
                if attempt >= self.retries or not retry_network:
                    kind = "timeout" if isinstance(exc, httpx.TimeoutException) else "network error"
                    raise BrightDataError(f"Bright Data {path}: {kind}") from exc
                attempt += 1
                await self._sleep(network_delay(attempt, self._rand))
                continue
            if response.status_code in _RETRY_STATUSES:
                # An answered error is not ambiguous: resending it starts nothing twice.
                if has_no_peers(response.text if response.content else ""):
                    if cooldowns < len(COOLDOWN_DELAYS):
                        await self._sleep(COOLDOWN_DELAYS[cooldowns])
                        cooldowns += 1
                        continue
                    raise BrightDataError(
                        f"Bright Data {path}: HTTP {response.status_code} {NO_PEERS}")
                if attempt < self.retries:
                    attempt += 1
                    await self._sleep(self._status_wait(response, attempt))
                    continue
            if response.status_code >= 400:
                raise BrightDataError(f"Bright Data {path}: HTTP {response.status_code}")
            return response

    @staticmethod
    def _dataset_params(
        dataset_id: str, method: str | None, limit_per_input: int | None
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"dataset_id": dataset_id, "include_errors": "true"}
        if method and method.startswith("discover_by_"):
            params.update({"type": "discover_new", "discover_by": method.removeprefix("discover_by_")})
            if limit_per_input is not None:
                params["limit_per_input"] = limit_per_input
        elif method not in {None, "collect_by_url"}:
            raise ValueError("method must be collect_by_url or discover_by_*")
        return params

    async def scrape_dataset(
        self, dataset_id: str, inputs: list[dict[str, Any]], *,
        method: str | None = None, limit_per_input: int | None = 10,
    ) -> CollectionOutput:
        if not inputs:
            raise ValueError("dataset inputs cannot be empty")
        # The synchronous endpoint holds the connection up to about a minute, then answers 202
        # with a snapshot_id (client timeout SYNC_TIMEOUT); never resend on a network timeout
        # (each resend would start a new, billed collection).
        for retry in range(len(COOLDOWN_DELAYS) + 1):
            response = await self._request(
                "POST", "/datasets/v3/scrape",
                params=self._dataset_params(dataset_id, method, limit_per_input),
                payload={"input": inputs}, retry_network=False,
            )
            payload = parse_body(response)
            # A clear no_peers answer (not an ambiguous timeout) may be sent again.
            if response.status_code == 202 or not has_no_peers(payload):
                break
            if retry < len(COOLDOWN_DELAYS):
                await self._sleep(COOLDOWN_DELAYS[retry])
        if response.status_code == 202:
            snapshot_id = payload.get("snapshot_id") if isinstance(payload, dict) else None
            if not snapshot_id:
                raise BrightDataError("Bright Data returned HTTP 202 without snapshot_id")
            record_call("datasets", rows=0, status="running", dataset_id=dataset_id,
                        snapshot_id=str(snapshot_id))
            return CollectionOutput(status="running", source_mode="live", snapshot_id=snapshot_id)
        rows = _data_rows(payload)
        record_usage("datasets", rows)
        record_call("datasets", rows=rows, status="ready", dataset_id=dataset_id)
        return CollectionOutput(status="ready", source_mode="live", data=payload,
                                warnings=[NO_PEERS] if has_no_peers(payload) else [])

    async def trigger_dataset(
        self, dataset_id: str, inputs: list[dict[str, Any]], *,
        method: str | None = None, limit_per_input: int | None = 10,
    ) -> str:
        if not inputs:
            raise ValueError("dataset inputs cannot be empty")
        for retry in range(len(COOLDOWN_DELAYS) + 1):
            response = await self._request(
                "POST", "/datasets/v3/trigger",
                params=self._dataset_params(dataset_id, method, limit_per_input),
                payload=inputs, retry_network=False,
            )
            payload = parse_body(response)
            snapshot = payload.get("snapshot_id") if isinstance(payload, dict) else None
            if snapshot or not has_no_peers(payload):
                break
            if retry < len(COOLDOWN_DELAYS):
                await self._sleep(COOLDOWN_DELAYS[retry])
        if not isinstance(payload, dict) or not payload.get("snapshot_id"):
            if has_no_peers(payload):
                raise BrightDataError(f"Bright Data trigger: {NO_PEERS}")
            raise BrightDataError("Bright Data trigger did not return snapshot_id")
        return str(payload["snapshot_id"])

    async def snapshot_progress(self, snapshot_id: str) -> dict[str, Any]:
        response = await self._request("GET", f"/datasets/v3/progress/{snapshot_id}")
        data = parse_body(response)
        if not isinstance(data, dict):
            raise BrightDataError("Bright Data progress response is not an object")
        return data

    async def snapshot_results(self, snapshot_id: str) -> CollectionOutput:
        for retry in range(len(COOLDOWN_DELAYS) + 1):
            response = await self._request(
                "GET", f"/datasets/v3/snapshot/{snapshot_id}", params={"format": "json"}
            )
            data = parse_body(response)
            # Only ever a re-read of the same snapshot: never a new, billed collection.
            if response.status_code == 202 or not has_no_peers(data):
                break
            if retry < len(COOLDOWN_DELAYS):
                await self._sleep(COOLDOWN_DELAYS[retry])
        if response.status_code == 202 or (
            isinstance(data, dict) and data.get("status") in {"starting", "running", "building"}
        ):
            return CollectionOutput(status="running", source_mode="live", snapshot_id=snapshot_id)
        if isinstance(data, dict) and data.get("status") in {"failed", "canceled"}:
            raise BrightDataError("Bright Data snapshot failed")
        rows = _data_rows(data)
        record_usage("datasets", rows)
        record_call("datasets", rows=rows, status="ready", snapshot_id=snapshot_id)
        return CollectionOutput(
            status="ready", source_mode="live", snapshot_id=snapshot_id, data=data,
            warnings=[NO_PEERS] if has_no_peers(data) else [],
        )

    async def serp(self, query: str, *, country: str = "us") -> str:
        if not self.serp_zone:
            raise BrightDataError("BRIGHTDATA_SERP_ZONE not configured")
        url = "https://www.google.com/search?" + urlencode({"q": query, "gl": country})
        response = await self._request(
            "POST", "/request", payload={"zone": self.serp_zone, "url": url, "format": "raw"}
        )
        record_usage("serp")
        record_call("serp", rows=1, status="ready")
        return response.text

    async def unlock(self, url: str) -> str:
        if not self.unlocker_zone:
            raise BrightDataError("BRIGHTDATA_UNLOCKER_ZONE not configured")
        if not url.startswith(("https://", "http://")):
            raise ValueError("unlock needs an absolute http(s) URL")
        response = await self._request(
            "POST", "/request",
            payload={"zone": self.unlocker_zone, "url": url, "format": "raw"},
        )
        text = response.text
        if blocked := block_reason(text):
            record_call("web_unlocker", rows=0, status="blocked")
            raise BrightDataError(f"unlocker_blocked:{blocked}")
        if len(text) < 2000 and text.lstrip().startswith("Residential Failed"):
            # Bright Data answers its own refusal (e.g. KYC required) with HTTP 200.
            reason = text.split(":", 1)[0].strip()
            kyc = " (KYC required for this site)" if "kyc" in text.lower() else ""
            raise BrightDataError(f"Web Unlocker refused {reason}{kyc}")
        record_usage("web_unlocker")
        record_call("web_unlocker", rows=1, status="ready")
        return text

    @staticmethod
    def load_fixture(path: str | Path, *, explicit_opt_in: bool = False) -> CollectionOutput:
        if not explicit_opt_in:
            raise BrightDataError("Fixture use must be explicitly enabled and labelled")
        fixture_path = Path(path)
        data = json.loads(fixture_path.read_text(encoding="utf-8"))
        return CollectionOutput(
            status="fixture", source_mode="fixture", data=data,
            warnings=[f"FIXTURE: loaded from {fixture_path.name}; not a live response"],
        )
