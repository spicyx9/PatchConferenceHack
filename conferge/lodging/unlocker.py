"""Hotel search pages fetched through the Bright Data Web Unlocker (zone from BRIGHTDATA_UNLOCKER_ZONE).

One fetch per site and query, never paginated. A price is kept only when it is literally in
the page (HTML or embedded JSON) for the requested dates; it is then ``indicative`` (a
search-page price, never verified). A hotel without such a price keeps ``total_price=None``
and the reason is counted in the RunReport warnings. Parsers live in ``unlocker_parsers``.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime
from decimal import Decimal
from typing import Any
from urllib.parse import quote

from conferge.core.brightdata import BrightDataClient, BrightDataError
from conferge.core.schemas import DiscoveryResult, Lodging, SourceRecord, SourceRef
from conferge.lodging._common import (
    content_hash,
    missing_credentials_report,
    now_utc,
    parse_money,
    report,
)
from conferge.lodging.models import LodgingQuery
from conferge.lodging.normalize import PriceQuote, build_lodging

PROVIDER = "unlocker"
TIMEOUT = 120.0
Clock = Callable[[], datetime]


def _city(q: LodgingQuery) -> str:
    return q.location or "San Francisco"


SEARCH_URLS: dict[str, Callable[[LodgingQuery], str]] = {
    "kayak": lambda q: (f"https://www.kayak.com/hotels/San-Francisco,CA-c13852/"
                        f"{q.check_in}/{q.check_out}/{q.adults}adults"),
    "hotels_com": lambda q: (f"https://www.hotels.com/Hotel-Search?destination="
                             f"{quote(_city(q) + ', California')}&startDate={q.check_in}"
                             f"&endDate={q.check_out}&adults={q.adults}&rooms={q.rooms}"),
    "expedia": lambda q: (f"https://www.expedia.com/Hotel-Search?destination="
                          f"{quote(_city(q) + ', California')}&startDate={q.check_in}"
                          f"&endDate={q.check_out}&adults={q.adults}&rooms={q.rooms}"),
    "marriott": lambda q: ("https://www.marriott.com/search/findHotels.mi?destinationAddress."
                           f"destination={quote(_city(q) + ', CA')}"
                           f"&fromDate={quote(f'{q.check_in:%m/%d/%Y}', safe='')}"
                           f"&toDate={quote(f'{q.check_out:%m/%d/%Y}', safe='')}"
                           f"&numberOfRooms={q.rooms}&numberOfAdults={q.adults}"),
    "hilton": lambda q: (f"https://www.hilton.com/en/search/?query={quote(_city(q) + ', CA')}"
                         f"&arrivalDate={q.check_in}&departureDate={q.check_out}"
                         f"&numRooms={q.rooms}&numAdults={q.adults}"),
}


def _parsers() -> dict[str, Callable[[str, str], list[dict[str, Any]]]]:
    from conferge.lodging.unlocker_parsers import PARSERS

    return PARSERS


class UnlockerHotelsSource:
    provider = PROVIDER

    def __init__(self, client: BrightDataClient | None = None, *,
                 sites: list[str] | None = None, timeout: float = TIMEOUT,
                 clock: Clock = now_utc) -> None:
        self._client = client if client is not None else BrightDataClient.from_env()
        self._owns = client is None
        self.sites = sites if sites is not None else list(SEARCH_URLS)
        self.timeout = timeout
        self.clock = clock

    async def aclose(self) -> None:
        if self._owns:
            await self._client.aclose()

    async def _site(self, site: str, q: LodgingQuery) -> tuple[list[SourceRecord], str | None, str]:
        url = SEARCH_URLS[site](q)
        try:
            html = await asyncio.wait_for(self._client.unlock(url), self.timeout)
        except (asyncio.TimeoutError, TimeoutError):
            return [], f"{site}: timeout after {self.timeout:.0f}s", url
        except BrightDataError as exc:
            return [], f"{site}: {exc}", url
        collected_at = self.clock()
        parser = _parsers().get(site)
        rows = parser(html, url) if parser else []
        zone = self._client.unlocker_zone
        records = []
        for row in rows:
            if not row.get("name"):
                continue
            key = f"{row.get('name')}|{row.get('address')}"
            records.append(SourceRecord(
                provider=PROVIDER, source_id=f"{site}:{content_hash(key)[:16]}",
                source_mode="live", collected_at=collected_at,
                payload={"site": site, "zone": zone, "search_url": url, "row": row,
                         "html_length": len(html)},
                source_url=row.get("url") or url, request_id=f"unlocker:{zone}:{site}",
                content_hash=content_hash(row),
            ))
        if not records:
            return [], f"{site}: no hotel parsed from {len(html)} bytes of HTML", url
        return records, None, url

    async def search(self, q: LodgingQuery) -> DiscoveryResult:
        started = self.clock()
        if not getattr(self._client, "_api_key", None):
            rep = missing_credentials_report(PROVIDER, started, "BRIGHTDATA_API_KEY")
            return DiscoveryResult(run_report=rep, errors=list(rep.errors))
        if not self._client.unlocker_zone:
            rep = missing_credentials_report(PROVIDER, started, "BRIGHTDATA_UNLOCKER_ZONE")
            return DiscoveryResult(run_report=rep, errors=list(rep.errors))
        results = await asyncio.gather(*(self._site(s, q) for s in self.sites))
        items: list[SourceRecord] = []
        errors: list[str] = []
        warnings: list[str] = []
        for site, (records, error, _url) in zip(self.sites, results, strict=True):
            if error:
                errors.append(error)
                continue
            priced = sum(1 for r in records if _row_price(r.payload["row"]) is not None)
            warnings.append(f"{site}: {len(records)} hotels, {priced} with a price in the page")
            if priced < len(records):
                warnings.append(f"{site}: {len(records) - priced} without a price in the HTML "
                                "for these dates; price left null")
            items.extend(records)
        blocked = [e for e in errors if "unlocker_blocked:" in e]
        # A bot wall is a degraded source (visible reason), never a stay with an empty price.
        status = ("ok" if items and not errors else
                  "degraded" if items or (errors and len(blocked) == len(errors)) else "failed")
        rep = report(PROVIDER, started, status=status,
                     termination="exhausted" if items else "error", source_mode="live",
                     fetched=len(items), unique=len({i.source_id for i in items}),
                     pages=len(self.sites), errors=errors, warnings=warnings)
        return DiscoveryResult(items=items, run_report=rep, errors=errors)

    async def fetch_details(self, ref: SourceRef) -> SourceRecord:
        raise BrightDataError("Web Unlocker search pages have no detail fetch")


def _row_price(row: dict[str, Any]) -> Decimal | None:
    return parse_money(row.get("nightly_price")) or parse_money(row.get("total_price"))


def to_lodging(record: SourceRecord, query: LodgingQuery, *, warnings: list[str] | None = None,
               now: datetime | None = None) -> Lodging | None:
    row = record.payload.get("row") or {}
    name = row.get("name")
    if not isinstance(name, str) or not name.strip():
        return None
    currency = row.get("currency") if isinstance(row.get("currency"), str) else None
    nightly, total = parse_money(row.get("nightly_price")), parse_money(row.get("total_price"))
    if total is not None:
        quote = PriceQuote(kind="dated_total", total=total, currency=currency)
    elif nightly is not None:
        quote = PriceQuote(kind="from_price", nightly_rate=nightly, currency=currency)
    else:
        quote = PriceQuote(currency=currency)
    stay = build_lodging(
        record, query, name=name.strip(), quote=quote, lodging_type="hotel",
        lat=row.get("lat"), lng=row.get("lng"),
        coordinate_precision="exact" if row.get("lat") is not None else "unknown",
        address=row.get("address"), city=row.get("city"),
        booking_url=row.get("url"), warnings=warnings, now=now,
    )
    if stay.total_price is not None or stay.nightly_avg is not None:
        # A search-page price is never more than indicative, whatever the page claims.
        stay = stay.model_copy(update={"price_status": "indicative"})
    return stay
