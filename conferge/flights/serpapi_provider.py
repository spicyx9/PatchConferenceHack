"""SerpApi Google Flights provider (secondary source, engine=google_flights).

Round trip flow: the first call lists outbound options only. For the cheapest
`max_returns` outbound options a second call with `departure_token` lists the
return options; their `price` is the total round-trip price. The cheapest
return per outbound becomes a 2-slice `FlightOffer`. Outbound options without
a fetched return are partial: no offer is built, they are counted in warnings.

A `booking_token` is not a URL and is never stored in models; `booking_url` is
`search_metadata.google_flights_url` (a search page) when present. The api key
is never logged and is scrubbed from every error message.
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from conferge.core.schemas import FlightOffer, RunReport, SourceEvidence
from conferge.flights.normalize import (
    NormalizationError,
    RawOffer,
    RawSegment,
    RawSlice,
    build_offer,
)

PROVIDER = "serpapi_google_flights"
ENDPOINT = "https://serpapi.com/search.json"
_TRAVEL_CLASS = {"economy": 1, "premium_economy": 2, "premium": 2, "business": 3, "first": 4}
_FLIGHT_NUMBER = re.compile(r"^\s*([A-Z0-9]{2})\s*(\d{1,4}[A-Z]?)\s*$")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def split_flight_number(value: Any) -> tuple[str | None, str | None]:
    """'BA 301' -> ('BA', 'BA301'). Unparseable -> (None, text without spaces)."""
    if not value:
        return None, None
    text = str(value).strip().upper()
    match = _FLIGHT_NUMBER.match(text)
    if not match:
        return None, text.replace(" ", "") or None
    return match.group(1), match.group(1) + match.group(2)


def _price_key(option: dict[str, Any]) -> Decimal:
    try:
        return Decimal(str(option.get("price")))
    except (InvalidOperation, ValueError):
        return Decimal("Infinity")


def _options(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows = (payload.get("best_flights") or []) + (payload.get("other_flights") or [])
    return [r for r in rows if isinstance(r, dict) and isinstance(r.get("flights"), list)]


def _slice(option: dict[str, Any]) -> RawSlice:
    segments = []
    for flight in option.get("flights") or []:
        if not isinstance(flight, dict):
            continue
        dep = flight.get("departure_airport") or {}
        arr = flight.get("arrival_airport") or {}
        carrier, number = split_flight_number(flight.get("flight_number"))
        segments.append(RawSegment(
            origin=dep.get("id"), destination=arr.get("id"),
            departure=dep.get("time"), arrival=arr.get("time"),
            marketing_carrier=carrier or flight.get("airline"),
            flight_number=number, aircraft=flight.get("airplane"),
            duration_minutes=flight.get("duration"),
        ))
    return RawSlice(segments=segments, duration_minutes=option.get("total_duration"))


def _http_url(value: Any) -> str | None:
    return value if isinstance(value, str) and value.startswith(("http://", "https://")) else None


class SerpApiError(Exception):
    pass


class SerpApiFlightsProvider:
    def __init__(
        self, api_key: str | None = None, client: httpx.AsyncClient | None = None,
        max_returns: int = 3, *, clock: Callable[[], datetime] = _now,
    ) -> None:
        self._api_key = api_key if api_key is not None else os.environ.get("SERPAPI_KEY")
        self._client = client
        self.max_returns = max_returns
        self.clock = clock

    def _sanitize(self, message: str) -> str:
        text = re.sub(r"api_key=[^&\s'\"]+", "api_key=***", message)
        if self._api_key:
            text = text.replace(self._api_key, "***")
        return text[:300]

    async def _get(self, client: httpx.AsyncClient, params: dict[str, Any]) -> dict[str, Any]:
        try:
            response = await client.get(ENDPOINT, params=params, timeout=60)
        except httpx.HTTPError as exc:
            raise SerpApiError(self._sanitize(f"{type(exc).__name__}: {exc}")) from None
        if response.status_code >= 400:
            detail = ""
            try:
                body = response.json()
                if isinstance(body, dict) and body.get("error"):
                    detail = f": {body['error']}"
            except ValueError:
                pass
            raise SerpApiError(self._sanitize(f"SerpApi HTTP {response.status_code}{detail}"))
        try:
            payload = response.json()
        except ValueError:
            raise SerpApiError("SerpApi returned non-JSON body") from None
        if not isinstance(payload, dict):
            raise SerpApiError("SerpApi returned unexpected JSON shape")
        if payload.get("error"):
            raise SerpApiError(self._sanitize(f"SerpApi error: {payload['error']}"))
        return payload

    def _report(
        self, started: datetime, status: str, termination: str, *, fetched: int = 0,
        unique: int = 0, pages: int = 0, errors: list[str] | None = None,
        warnings: list[str] | None = None,
    ) -> RunReport:
        return RunReport(
            provider=PROVIDER, started_at=started, finished_at=max(self.clock(), started),
            status=status, termination=termination, source_mode="live",
            fetched_count=fetched, unique_count=unique, pages=pages,
            errors=errors or [], warnings=warnings or [],
        )

    async def search_round_trip(
        self, origin: str, destination: str, departure: date, return_date: date,
        *, adults: int = 1, cabin: str = "economy",
    ) -> tuple[list[FlightOffer], RunReport]:
        started = self.clock()
        if not self._api_key:
            return [], self._report(started, "failed", "error", errors=["SERPAPI_KEY missing"])
        params: dict[str, Any] = {
            "engine": "google_flights", "departure_id": origin, "arrival_id": destination,
            "outbound_date": departure.isoformat(), "return_date": return_date.isoformat(),
            "type": 1, "adults": adults,
            "travel_class": _TRAVEL_CLASS.get(cabin.lower(), 1),
            "currency": "USD", "hl": "en", "gl": "us", "no_cache": "true",
            "api_key": self._api_key,
        }
        client = self._client or httpx.AsyncClient()
        try:
            return await self._search(client, params, started)
        finally:
            if self._client is None:
                await client.aclose()

    async def _search(
        self, client: httpx.AsyncClient, params: dict[str, Any], started: datetime,
    ) -> tuple[list[FlightOffer], RunReport]:
        pages = 1
        try:
            first = await self._get(client, params)
        except SerpApiError as exc:
            return [], self._report(started, "failed", "error", pages=pages, errors=[str(exc)])
        outbound = sorted(_options(first), key=_price_key)
        first_meta = first.get("search_metadata") or {}
        warnings: list[str] = []
        errors: list[str] = []
        offers: dict[str, FlightOffer] = {}
        return_failed = False
        with_token = [o for o in outbound if o.get("departure_token")]
        if len(with_token) < len(outbound):
            warnings.append(
                f"partial_roundtrip: {len(outbound) - len(with_token)} outbound option(s) "
                "without departure_token"
            )
        selected, skipped = with_token[: self.max_returns], with_token[self.max_returns:]
        if skipped:
            warnings.append(
                f"partial_roundtrip: {len(skipped)} outbound option(s) not priced as round "
                f"trip (max_returns={self.max_returns})"
            )
        for option in selected:
            pages += 1
            try:
                ret = await self._get(client, {**params, "departure_token": option["departure_token"]})
            except SerpApiError as exc:
                return_failed = True
                warnings.append(f"partial_roundtrip: return fetch failed: {exc}")
                continue
            collected_at = self.clock()
            returns = sorted(_options(ret), key=_price_key)
            if not returns:
                warnings.append("partial_roundtrip: no return option for an outbound option")
                continue
            best = returns[0]
            meta = ret.get("search_metadata") or {}
            url = _http_url(meta.get("google_flights_url")) or _http_url(
                first_meta.get("google_flights_url"))
            raw_warnings = []
            if best.get("booking_token"):
                raw_warnings.append(
                    "booking_options_available: via SerpApi booking_token (token not stored)")
            raw = RawOffer(
                provider=PROVIDER, slices=[_slice(option), _slice(best)],
                trip_type="round_trip", price=best.get("price"), currency="USD",
                price_scope="unknown",
                booking_url=url, booking_url_type="google_flights_search" if url else "unknown",
                evidence=[SourceEvidence(
                    provider=PROVIDER, source_mode="live", source_url=url,
                    collected_at=collected_at,
                    raw_ref=meta.get("id") or first_meta.get("id"),
                )],
                warnings=raw_warnings,
            )
            try:
                offer = build_offer(raw, collected_at)
            except (NormalizationError, ValueError) as exc:
                warnings.append(f"normalization_failed: {exc}")
                continue
            offers.setdefault(offer.id, offer)
        result = list(offers.values())
        partial = any(w.startswith("partial_roundtrip") for w in warnings)
        if not result:
            status, termination = "failed", "error" if return_failed else "exhausted"
            errors.append("zero round-trip offers from SerpApi")
        elif return_failed:
            status, termination = "degraded", "error"
        elif partial:
            status, termination = "degraded", "page_cap"
        elif any(w.startswith("normalization_failed") for w in warnings):
            status, termination = "degraded", "schema_changed"
        else:
            status, termination = "ok", "exhausted"
        return result, self._report(
            started, status, termination, fetched=len(outbound),
            unique=min(len(result), len(outbound)), pages=pages,
            errors=errors, warnings=warnings,
        )
