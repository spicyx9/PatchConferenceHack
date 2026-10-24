"""Uber public price estimator through Bright Data Web Unlocker (best-effort).

The estimator page is JavaScript rendered; the raw HTML usually carries no fare.
We only accept a dollar range that sits within 200 characters of "UberX". If none is
found the run is degraded (schema_changed) with no leg. There is no distance-based
fare table fallback: an unknown fare stays unknown.

URL: the public estimator plus pickup/dropoff "lat,lng" query params. Uber does not
document these params; they are a best-effort hint and may be ignored by the page.
"""

from __future__ import annotations

import re
from datetime import datetime
from urllib.parse import urlencode

from conferge.core.brightdata import BrightDataClient, BrightDataError
from conferge.core.schemas import SourceEvidence
from conferge.travel.models import Mode, Place, Price, ProviderOutcome, RouteLeg, utcnow
from conferge.travel.providers.base import failed, report

NAME = "uber_estimator"
ESTIMATOR_URL = "https://www.uber.com/global/en/price-estimate/"
NO_FARE_WARNING = "Uber estimator returned no parseable UberX fare (JS-rendered page)"
FARE_RE = re.compile(r"\$(\d{1,3}(?:\.\d{2})?)\s*[-\u2013]\s*\$?(\d{1,3}(?:\.\d{2})?)")
UBERX_RE = re.compile(r"uberx\b", re.IGNORECASE)
CONTEXT_CHARS = 200


def build_url(origin: Place, destination: Place) -> str:
    query = urlencode({
        "pickup": f"{origin.latitude},{origin.longitude}",
        "dropoff": f"{destination.latitude},{destination.longitude}",
    })
    return f"{ESTIMATOR_URL}?{query}"


def parse_uberx_range(html: str) -> tuple[str, str] | None:
    """Return (low, high) of the first fare range within 200 chars of 'UberX'."""
    anchors = [m.start() for m in UBERX_RE.finditer(html)]
    if not anchors:
        return None
    for match in FARE_RE.finditer(html):
        if any(abs(match.start() - a) <= CONTEXT_CHARS for a in anchors):
            low, high = match.group(1), match.group(2)
            if float(low) <= float(high):
                return low, high
    return None


def _sanitize(message: str, secret: str | None) -> str:
    if secret:
        message = message.replace(secret, "***")
    return message


class UberEstimateProvider:
    name = NAME
    modes: frozenset[Mode] = frozenset({"rideshare"})

    def __init__(self, client: BrightDataClient | None = None) -> None:
        self._client = client

    async def route(
        self, origin: Place, destination: Place, *, mode: Mode,
        depart_at: datetime | None = None,
    ) -> ProviderOutcome:
        started = utcnow()
        if mode not in self.modes:
            return failed(NAME, started, f"uber_estimator does not support mode {mode!r}")
        url = build_url(origin, destination)
        own = self._client is None
        client = self._client or BrightDataClient.from_env()
        try:
            html = await client.unlock(url)
        except BrightDataError as exc:
            message = _sanitize(str(exc), getattr(client, "_api_key", None))
            termination = "blocked" if "HTTP 403" in message else "error"
            return failed(NAME, started, f"uber estimator: {message}", termination=termination)
        finally:
            if own:
                await client.aclose()
        fare = parse_uberx_range(html)
        if fare is None:
            return ProviderOutcome(
                legs=[],
                run_report=report(
                    NAME, started, status="degraded", termination="schema_changed",
                    pages=1, warnings=[NO_FARE_WARNING],
                ),
            )
        low, high = fare
        collected = utcnow()
        leg = RouteLeg(
            from_place=origin, to_place=destination, mode="rideshare",
            price=Price(
                amount=low, currency="USD", status="estimate", fare_class="uberx_range_low",
                note=f"Uber public estimator range {low}-{high} USD",
            ),
            provider=NAME, source_mode="live", collected_at=collected, source_url=url,
            warnings=["UberX fare is a public estimator range; duration unknown"],
            evidence=[SourceEvidence(
                provider=NAME, source_mode="live", source_url=url, collected_at=collected,
            )],
        )
        return ProviderOutcome(
            legs=[leg],
            run_report=report(NAME, started, status="ok", termination="exhausted",
                              fetched=1, pages=1),
        )
