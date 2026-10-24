"""Single Bright Data HTTP client shared by all source adapters.

No automatic fabrication: fixture fallback is opt-in and visibly labelled.
Secrets are never interpolated into logs or exception messages.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlencode

import httpx
from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)
_RETRY_STATUSES = {429, 500, 502, 503, 504}

BrightDataApi = Literal["datasets", "web_unlocker", "serp"]
# Process-wide count of what Bright Data actually returned (successful responses only):
# dataset rows, Web Unlocker pages, SERP result pages. Shown on the demo home screen.
_USAGE: dict[str, int] = {"datasets": 0, "web_unlocker": 0, "serp": 0}


def record_usage(api: BrightDataApi, count: int = 1) -> None:
    _USAGE[api] = _USAGE.get(api, 0) + max(count, 0)


def usage() -> dict[str, int]:
    return {**_USAGE, "total": sum(_USAGE.values())}


def reset_usage() -> None:
    for key in _USAGE:
        _USAGE[key] = 0


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
    ) -> None:
        self._api_key = api_key
        self.serp_zone = serp_zone
        self.unlocker_zone = unlocker_zone
        self._client = client or httpx.AsyncClient(
            base_url="https://api.brightdata.com", timeout=30.0
        )
        self._owns_client = client is None
        self.retries = retries

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

    async def _request(
        self, method: str, path: str, *, params: dict[str, Any] | None = None,
        payload: Any = None,
    ) -> httpx.Response:
        if not self._api_key:
            raise BrightDataError("Bright Data key missing; set BRIGHTDATA_API_KEY")
        for attempt in range(self.retries + 1):
            try:
                logger.info("brightdata.request", extra={"endpoint": path, "attempt": attempt + 1})
                response = await self._client.request(
                    method, path, params=params, json=payload,
                    headers={"Authorization": f"Bearer {self._api_key}"},
                )
                if response.status_code in _RETRY_STATUSES and attempt < self.retries:
                    await asyncio.sleep(min(2 ** attempt, 4))
                    continue
                if response.status_code >= 400:
                    raise BrightDataError(
                        f"Bright Data {path}: HTTP {response.status_code}"
                    )
                return response
            except (httpx.RequestError, httpx.TimeoutException) as exc:
                if attempt == self.retries:
                    raise BrightDataError(f"Bright Data {path}: network error") from exc
                await asyncio.sleep(min(2 ** attempt, 4))
        raise BrightDataError(f"Bright Data {path}: exhausted retries")

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
        response = await self._request(
            "POST", "/datasets/v3/scrape",
            params=self._dataset_params(dataset_id, method, limit_per_input),
            payload={"input": inputs},
        )
        payload = response.json()
        if response.status_code == 202:
            snapshot_id = payload.get("snapshot_id") if isinstance(payload, dict) else None
            if not snapshot_id:
                raise BrightDataError("Bright Data returned HTTP 202 without snapshot_id")
            return CollectionOutput(status="running", source_mode="live", snapshot_id=snapshot_id)
        record_usage("datasets", len(payload) if isinstance(payload, list) else 1)
        return CollectionOutput(status="ready", source_mode="live", data=payload)

    async def trigger_dataset(
        self, dataset_id: str, inputs: list[dict[str, Any]], *,
        method: str | None = None, limit_per_input: int | None = 10,
    ) -> str:
        if not inputs:
            raise ValueError("dataset inputs cannot be empty")
        response = await self._request(
            "POST", "/datasets/v3/trigger",
            params=self._dataset_params(dataset_id, method, limit_per_input),
            payload=inputs,
        )
        payload = response.json()
        if not isinstance(payload, dict) or not payload.get("snapshot_id"):
            raise BrightDataError("Bright Data trigger did not return snapshot_id")
        return str(payload["snapshot_id"])

    async def snapshot_progress(self, snapshot_id: str) -> dict[str, Any]:
        response = await self._request("GET", f"/datasets/v3/progress/{snapshot_id}")
        data = response.json()
        if not isinstance(data, dict):
            raise BrightDataError("Bright Data progress response is not an object")
        return data

    async def snapshot_results(self, snapshot_id: str) -> CollectionOutput:
        response = await self._request(
            "GET", f"/datasets/v3/snapshot/{snapshot_id}", params={"format": "json"}
        )
        data = response.json()
        if response.status_code == 202 or (
            isinstance(data, dict) and data.get("status") in {"starting", "running", "building"}
        ):
            return CollectionOutput(status="running", source_mode="live", snapshot_id=snapshot_id)
        if isinstance(data, dict) and data.get("status") in {"failed", "canceled"}:
            raise BrightDataError("Bright Data snapshot failed")
        record_usage("datasets", len(data) if isinstance(data, list) else 1)
        return CollectionOutput(
            status="ready", source_mode="live", snapshot_id=snapshot_id, data=data
        )

    async def serp(self, query: str, *, country: str = "us") -> str:
        if not self.serp_zone:
            raise BrightDataError("BRIGHTDATA_SERP_ZONE not configured")
        url = "https://www.google.com/search?" + urlencode({"q": query, "gl": country})
        response = await self._request(
            "POST", "/request", payload={"zone": self.serp_zone, "url": url, "format": "raw"}
        )
        record_usage("serp")
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
        record_usage("web_unlocker")
        return response.text

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
