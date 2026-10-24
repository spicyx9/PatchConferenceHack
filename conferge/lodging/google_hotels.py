"""Google Hotels via Bright Data dataset ``gd_mg3gjfmg12tc2n5d4d`` (metasearch).

Inputs and output field names come from the public Bright Data catalogue
(raw/lodging/schemas/gd_mg3gjfmg12tc2n5d4d.json): ``discover_by_search`` takes
``search_term``, ``check_in_date``, ``check_out_date``, ``guest_number``, ``country`` and
``currency``; rows carry ``url``, ``hotel_id``, ``hotel_name``, ``rating``, ``review_count``
(text), ``address``, the echoed stay, ``booking_options``, ``lat``, ``long`` and ``currency``.

UNVERIFIED LIVE: the nested shape of ``booking_options`` is not documented by the catalogue
and no Bright Data key was available on 2026-10-24, so ``booking_options()`` parses it
defensively (several key spellings, plain strings) and keeps only prices whose scope (stay
total or per night) is explicit. An unqualified price is kept as raw text only.

Google Hotels is a metasearch: offers belong to third-party sellers, so this adapter never
produces ``verified_bookable``. The Google URL is taken as returned, never built by hand.

SerpApi ``engine=google_hotels`` fallback is NOT implemented: no SERPAPI_KEY is available
and the hackathon sponsor technology is Bright Data.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import datetime
from decimal import Decimal
from typing import Any

from conferge.core.brightdata import BrightDataClient, BrightDataError
from conferge.core.schemas import (
    DiscoveryQuery,
    DiscoveryResult,
    Lodging,
    SourceRecord,
    SourceRef,
)
from conferge.lodging._bd import SnapshotPending, collect, has_key
from conferge.lodging._common import (
    DATASET_GOOGLE_HOTELS,
    GOOGLE_HOTELS,
    MARKET_CONTEXT,
    content_hash,
    missing_credentials_report,
    now_utc,
    parse_date,
    parse_float,
    parse_int,
    parse_money,
    report,
)
from conferge.lodging.models import LodgingQuery
from conferge.lodging.normalize import PriceQuote, build_lodging

PROVIDER = GOOGLE_HOTELS

_VENDOR_KEYS = ("source", "vendor", "name", "provider", "seller", "title")
_URL_KEYS = ("link", "url", "booking_link")
_PRICE_KEYS = (
    "total_price", "price_total", "total", "total_rate", "rate_per_night", "nightly_price",
    "price_per_night", "price", "before_taxes_fees", "after_taxes",
)
_NESTED_PRICE_KEYS = ("extracted_lowest", "lowest", "extracted_price", "price", "amount", "value")
_FOR_NIGHTS_RE = re.compile(r"for\s+\d+\s+nights?", re.IGNORECASE)
_HTTP_RE = re.compile(r"HTTP (\d{3})")
_CURRENCY_RE = re.compile(r"^[A-Z]{3}$")


def _currency(value: Any) -> str | None:
    if isinstance(value, str) and _CURRENCY_RE.match(value.strip()):
        return value.strip()
    return None


def _http_url(value: Any) -> str | None:
    if isinstance(value, str) and value.strip().startswith(("https://", "http://")):
        return value.strip()
    return None


def _scope(key: str, text: str | None) -> str:
    """Return ``total``, ``nightly`` or ``unknown`` from the key name, then the price text."""
    low_key = key.lower()
    if "total" in low_key:
        return "total"
    if "night" in low_key:
        return "nightly"
    if text:
        low = text.lower()
        if _FOR_NIGHTS_RE.search(low):
            return "total"
        if "total" in low and "night" in low:
            return "unknown"  # two amounts in one string: ambiguous, keep raw only
        if "total" in low:
            return "total"
        if "night" in low:
            return "nightly"
    return "unknown"


def _price_value(value: Any) -> tuple[Decimal | None, str | None]:
    """(amount, raw text) for a scalar or a SerpApi-like nested ``{lowest: ...}`` object."""
    if isinstance(value, dict):
        for key in _NESTED_PRICE_KEYS:
            if key in value:
                amount, text = _price_value(value[key])
                if amount is not None:
                    raw = value.get("lowest") if isinstance(value.get("lowest"), str) else text
                    return amount, raw
        return None, None
    if isinstance(value, str):
        return parse_money(value), value.strip() or None
    if isinstance(value, (int, float, Decimal)) and not isinstance(value, bool):
        return parse_money(value), str(value)
    return None, None


def _normalize_option(option: Any) -> dict[str, Any] | None:
    out: dict[str, Any] = {"vendor": None, "total": None, "nightly": None, "url": None,
                           "currency": None, "raw_price_text": None}
    if isinstance(option, str):
        amount, text = _price_value(option)
        if amount is None:
            return None
        out["raw_price_text"] = text
        scope = _scope("", text)
        if scope != "unknown":
            out[scope] = amount
        return out
    if not isinstance(option, dict):
        return None
    for key in _VENDOR_KEYS:
        if isinstance(option.get(key), str) and option[key].strip():
            out["vendor"] = option[key].strip()
            break
    for key in _URL_KEYS:
        url = _http_url(option.get(key))
        if url:
            out["url"] = url
            break
    out["currency"] = _currency(option.get("currency"))
    for key in _PRICE_KEYS:
        if key not in option:
            continue
        amount, text = _price_value(option[key])
        if amount is None:
            continue
        if out["raw_price_text"] is None:
            out["raw_price_text"] = text
        scope = _scope(key, text if isinstance(option[key], str) else None)
        if scope != "unknown" and out[scope] is None:
            out[scope] = amount
    if out["raw_price_text"] is None and out["vendor"] is None and out["url"] is None:
        return None
    return out


def _row(record: SourceRecord) -> dict[str, Any]:
    payload = record.payload or {}
    row = payload.get("search") or payload.get("detail") or {}
    return row if isinstance(row, dict) else {}


def booking_options(record: SourceRecord) -> list[dict]:
    """Normalized seller offers. Zero or unparseable prices are dropped, never repaired."""
    raw = _row(record).get("booking_options")
    if isinstance(raw, dict):
        raw = [raw]
    if not isinstance(raw, list):
        return []
    return [opt for opt in (_normalize_option(o) for o in raw) if opt is not None]


def to_lodging(
    record: SourceRecord, query: LodgingQuery, *, warnings: list[str] | None = None,
    now: datetime | None = None,
) -> Lodging | None:
    row = _row(record)
    name = row.get("hotel_name")
    if not isinstance(name, str) or not name.strip():
        return None
    sink = warnings if warnings is not None else []
    row_currency = _currency(row.get("currency"))
    options = booking_options(record)
    usable = []
    for opt in options:
        if row_currency and opt["currency"] and opt["currency"] != row_currency:
            sink.append(f"{PROVIDER}:{record.source_id}: option {opt['vendor']!r} in "
                        f"{opt['currency']} != row {row_currency}; ignored")
            continue
        usable.append(opt)
    totals = [o for o in usable if o["total"] is not None]
    nightlies = [o for o in usable if o["nightly"] is not None]
    chosen: dict[str, Any] | None = None
    if totals:
        chosen = min(totals, key=lambda o: o["total"])
        quote = PriceQuote(kind="dated_total", total=chosen["total"],
                           currency=row_currency or chosen["currency"], includes_all_fees=None)
    elif nightlies:
        chosen = min(nightlies, key=lambda o: o["nightly"])
        quote = PriceQuote(kind="from_price", nightly_rate=chosen["nightly"],
                           currency=row_currency or chosen["currency"])
    else:
        quote = PriceQuote(currency=row_currency)
    booking_url = (chosen or {}).get("url") or (
        str(record.source_url) if record.source_url else None)
    lat, lng = parse_float(row.get("lat")), parse_float(row.get("long"))
    rating = parse_float(row.get("rating"))
    address = row.get("address") if isinstance(row.get("address"), str) else None
    return build_lodging(
        record, query, name=name.strip(), quote=quote, lodging_type="hotel",
        availability="unknown", lat=lat, lng=lng,
        coordinate_precision="exact" if lat is not None and lng is not None else "unknown",
        address=address, rating=rating, rating_scale=5,
        rating_count=parse_int(row.get("review_count")), booking_url=booking_url,
        echoed_check_in=parse_date(row.get("check_in_date")),
        echoed_check_out=parse_date(row.get("check_out_date")),
        echoed_adults=parse_int(row.get("guest_number")),
        warnings=sink, now=now,
    )


def _error_termination(exc: BrightDataError) -> str:
    match = _HTTP_RE.search(str(exc))
    code = match.group(1) if match else None
    if code == "403":
        return "blocked"
    if code == "429":
        return "rate_limited"
    return "error"


class GoogleHotelsSource:
    def __init__(
        self, client: BrightDataClient | None = None, *, poll_interval: float = 5.0,
        max_wait: float = 240.0, clock: Callable[[], datetime] = now_utc,
    ) -> None:
        self._owns_client = client is None
        self.client = client if client is not None else BrightDataClient.from_env()
        self.poll_interval = poll_interval
        self.max_wait = max_wait
        self.clock = clock

    async def aclose(self) -> None:
        if self._owns_client:
            await self.client.aclose()

    def _record(self, row: dict[str, Any], *, kind: str, snapshot_id: str | None,
                query: LodgingQuery | None) -> SourceRecord | None:
        hotel_id = row.get("hotel_id")
        url = _http_url(row.get("url"))
        if hotel_id not in (None, ""):
            source_id = str(hotel_id)
        elif url:
            source_id = "url:" + content_hash(url).removeprefix("sha256:")[:16]
        else:
            return None
        payload: dict[str, Any] = {kind: row, "market_context": MARKET_CONTEXT,
                                   "dataset_id": DATASET_GOOGLE_HOTELS}
        if query is not None:
            payload["query"] = {"check_in": query.check_in.isoformat(),
                                "check_out": query.check_out.isoformat(),
                                "adults": query.adults, "currency": query.currency}
        return SourceRecord(
            provider=PROVIDER, source_id=source_id, source_mode="live",
            collected_at=self.clock(), source_url=url, request_id=snapshot_id,
            content_hash=content_hash(row), payload=payload,
        )

    async def search(self, q: LodgingQuery) -> DiscoveryResult:
        started = self.clock()
        if not has_key(self.client):
            rep = missing_credentials_report(PROVIDER, started, "BRIGHTDATA_API_KEY")
            return DiscoveryResult(run_report=rep, errors=list(rep.errors))
        inputs = [{
            "search_term": q.search_term, "check_in_date": q.check_in.isoformat(),
            "check_out_date": q.check_out.isoformat(), "guest_number": q.adults,
            "country": q.country, "currency": q.currency,
        }]
        try:
            got = await collect(self.client, DATASET_GOOGLE_HOTELS, inputs,
                                method="discover_by_search", limit_per_input=q.limit,
                                poll_interval=self.poll_interval, max_wait=self.max_wait)
        except SnapshotPending as exc:
            rep = report(PROVIDER, started, status="failed", termination="error",
                         errors=[str(exc)],
                         warnings=[f"snapshot {exc.snapshot_id} pending; fetch it later"])
            return DiscoveryResult(run_report=rep, errors=list(rep.errors))
        except BrightDataError as exc:
            rep = report(PROVIDER, started, status="failed",
                         termination=_error_termination(exc), errors=[str(exc)])  # type: ignore[arg-type]
            return DiscoveryResult(run_report=rep, errors=list(rep.errors))

        from conferge.lodging.detail_candidates import hydrate

        hydrated, detail_warnings, detail_partial, detail_calls = await hydrate(
            got.rows, client=self.client, dataset=DATASET_GOOGLE_HOTELS, site="google",
            limit=q.limit, country=q.country, poll_interval=self.poll_interval,
            max_wait=self.max_wait,
        )
        warnings = [*got.warnings, *detail_warnings]
        items: list[SourceRecord] = []
        seen: set[str] = set()
        skipped = duplicates = 0
        for row in hydrated:
            record = self._record(row, kind="search",
                                  snapshot_id=row.get("_detail_snapshot_id", got.snapshot_id), query=q)
            if record is None:
                skipped += 1
                continue
            if record.source_id in seen:
                duplicates += 1
                continue
            seen.add(record.source_id)
            items.append(record)
        if skipped:
            warnings.append(f"{skipped} row(s) without hotel_id or url skipped")
        if duplicates:
            warnings.append(f"{duplicates} duplicate row(s) merged by hotel_id/url")
        returned = len(got.rows) + got.error_rows
        if not got.rows:
            warnings.append("zero results")
            status, termination = "degraded", "error"
        elif returned >= q.limit:
            warnings.append(f"page_cap: {returned} rows == limit {q.limit}; more may exist")
            status, termination = "degraded", "page_cap"
        else:
            status = "degraded" if (got.error_rows or skipped or detail_partial) else "ok"
            termination = "exhausted"
        rep = report(PROVIDER, started, status=status, termination=termination,  # type: ignore[arg-type]
                     fetched=max(len(got.rows), len(items)), unique=len(items), pages=1 + detail_calls, warnings=warnings,
                     finished_at=self.clock())
        return DiscoveryResult(items=items, run_report=rep)

    async def discover(self, query: DiscoveryQuery) -> DiscoveryResult:
        started = self.clock()
        try:
            q = LodgingQuery.from_discovery(query)
        except ValueError as exc:
            rep = report(PROVIDER, started, status="failed", termination="error",
                         errors=[f"invalid lodging query: {exc}"])
            return DiscoveryResult(run_report=rep, errors=list(rep.errors))
        return await self.search(q)

    async def fetch_details(self, ref: SourceRef) -> SourceRecord:
        if ref.url is None:
            raise BrightDataError("google_hotels fetch_details needs ref.url")
        got = await collect(self.client, DATASET_GOOGLE_HOTELS, [{"url": str(ref.url)}],
                            method="collect_by_url", limit_per_input=None,
                            poll_interval=self.poll_interval, max_wait=self.max_wait)
        for row in got.rows:
            record = self._record(row, kind="detail", snapshot_id=got.snapshot_id, query=None)
            if record is not None:
                return record
        raise BrightDataError("google_hotels collect_by_url returned no usable row")
