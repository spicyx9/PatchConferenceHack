"""Booking.com lodging source through Bright Data datasets (core.brightdata only).

Search: dataset ``gd_m4bf7a917zfezv9d5`` (collect_by_url, no discover method) with search
inputs (location, ISO Z check_in/check_out, adults, children, rooms, currency, country).
Verification: dataset ``gd_mdy9ld3p1e0oqlj9g4`` on the hotel page URL rebuilt with the exact
stay (``stay_url``) and ``sb_price_type=total``.

Payload field names come from the Bright Data public catalogue
(raw/lodging/schemas/gd_m4bf7a917zfezv9d5.json, gd_mdy9ld3p1e0oqlj9g4.json) and the public
sample (booking_sample_head.csv: ``final_price`` is the stay total, ``check_in`` echoed as
``"2025-01-01T00:00:00.000Z"``, ``tax_description`` empty). Live behaviour is UNVERIFIED:
no Bright Data key was available on 2026-10-24. The nested shape of the detail ``pricing``
and ``availability`` arrays is undocumented, so their parsing is defensive and only
promotes a price to ``verified`` on explicit signals.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

from pydantic import ValidationError

from conferge.core.brightdata import BrightDataClient, BrightDataError
from conferge.core.schemas import (
    DiscoveryQuery,
    DiscoveryResult,
    Lodging,
    RunReport,
    SourceEvidence,
    SourceRecord,
    SourceRef,
)
from conferge.lodging._bd import SnapshotPending, collect, has_key
from conferge.lodging._common import (
    BOOKING,
    DATASET_BOOKING_DETAIL,
    DATASET_BOOKING_SEARCH,
    MARKET_CONTEXT,
    content_hash,
    missing_credentials_report,
    now_utc,
    parse_bool,
    parse_date,
    parse_float,
    parse_int,
    parse_money,
    report,
)
from conferge.lodging.models import LodgingQuery
from conferge.lodging.normalize import PriceQuote, build_lodging

PROVIDER = BOOKING
VERIFY_PROVIDER = f"{BOOKING}:verify"
KEY_NAME = "BRIGHTDATA_API_KEY"

_PRICE_KEYS = ("total_price", "price_total", "final_price", "price", "amount")
_TAX_FLAG_KEYS = ("includes_taxes", "taxes_included", "includes_taxes_and_fees",
                  "tax_included", "taxes_and_fees_included")
_INCLUDED_TEXT = ("includes taxes and fees", "including taxes and fees",
                  "taxes and fees included", "including taxes", "includes taxes",
                  "incl. taxes", "taxes included")
_UNAVAILABLE_TEXT = ("no availability", "not available", "sold out", "unavailable")
_ADDED_TAX_RE = re.compile(
    r"\+\s*(?P<amount>[^\d\s+]{0,4}\s?\d[\d,]*(?:\.\d+)?)\s*(?P<label>taxes\s*(?:and|&)\s*fees"
    r"|taxes|fees)", re.IGNORECASE,
)


def _iso_z(day: date) -> str:
    return f"{day.isoformat()}T00:00:00.000Z"


def stay_url(page_url: str, q: LodgingQuery) -> str:
    """Hotel page URL with the exact stay; any other query parameter is dropped."""
    parts = urlsplit(page_url)
    params = {
        "checkin": q.check_in.isoformat(),
        "checkout": q.check_out.isoformat(),
        "group_adults": str(q.adults),
        "no_rooms": str(q.rooms),
        "group_children": str(q.children),
        "selected_currency": q.currency,
        "sb_price_type": "total",
    }
    return urlunsplit((parts.scheme or "https", parts.netloc, parts.path, urlencode(params), ""))


def _slug(url: Any) -> str | None:
    if not isinstance(url, str) or not url:
        return None
    segment = urlsplit(url).path.rstrip("/").rsplit("/", 1)[-1]
    slug = segment.split(".", 1)[0]
    return slug.lower() or None


def _termination_for(exc: BrightDataError) -> str:
    message = str(exc)
    if "HTTP 429" in message:
        return "rate_limited"
    if "HTTP 403" in message:
        return "blocked"
    return "error"


def _query_echo(q: LodgingQuery) -> dict[str, Any]:
    return {"check_in": q.check_in.isoformat(), "check_out": q.check_out.isoformat(),
            "adults": q.adults, "children": q.children, "rooms": q.rooms,
            "currency": q.currency}


def _parse_dt(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


class BookingSource:
    """Booking.com search + detail verification. Never raises from search/verify/discover."""

    def __init__(
        self, client: BrightDataClient | None = None, *, poll_interval: float = 5.0,
        max_wait: float = 240.0, clock: Callable[[], datetime] = now_utc,
    ) -> None:
        self._owns = client is None
        self._client = client if client is not None else BrightDataClient.from_env()
        self._poll_interval = poll_interval
        self._max_wait = max_wait
        self._clock = clock

    async def aclose(self) -> None:
        if self._owns:
            await self._client.aclose()

    def _failed(self, provider: str, started: datetime, exc: BrightDataError) -> RunReport:
        warnings = []
        if isinstance(exc, SnapshotPending):
            warnings.append(f"snapshot {exc.snapshot_id} still running; fetch it later")
            termination = "error"
        else:
            termination = _termination_for(exc)
        return report(provider, started, status="failed", termination=termination,
                      errors=[str(exc)], warnings=warnings, finished_at=self._clock())

    async def search(self, q: LodgingQuery) -> DiscoveryResult:
        started = self._clock()
        if not has_key(self._client):
            rep = missing_credentials_report(PROVIDER, started, KEY_NAME)
            return DiscoveryResult(items=[], run_report=rep, errors=list(rep.errors))
        inputs = [{
            "url": "https://www.booking.com", "location": q.location,
            "check_in": _iso_z(q.check_in), "check_out": _iso_z(q.check_out),
            "adults": q.adults, "children": q.children, "rooms": q.rooms,
            "currency": q.currency, "country": q.country,
        }]
        try:
            got = await collect(self._client, DATASET_BOOKING_SEARCH, inputs, method=None,
                                limit_per_input=q.limit, poll_interval=self._poll_interval,
                                max_wait=self._max_wait)
        except BrightDataError as exc:
            rep = self._failed(PROVIDER, started, exc)
            return DiscoveryResult(items=[], run_report=rep, errors=list(rep.errors))

        collected_at = self._clock()
        warnings = list(got.warnings)
        items: list[SourceRecord] = []
        seen: set[str] = set()
        missing_id = 0
        expected: int | None = None
        for row in got.rows:
            total = parse_int(row.get("total_listings_found"))
            if total is not None:
                expected = max(expected or 0, total)
            if row.get("id") in (None, ""):
                missing_id += 1
                continue
            source_id = str(row["id"])
            if source_id in seen:
                continue
            seen.add(source_id)
            items.append(self._record(row, source_id, q, collected_at, got.snapshot_id))
        if missing_id:
            warnings.append(f"{missing_id} row(s) without id skipped")
        fetched = len(got.rows)
        if fetched == 0:
            status, termination = "degraded", "error"
            warnings.append("zero results")
        elif expected is not None and expected > fetched:
            status, termination = "degraded", "page_cap"
            warnings.append(f"{fetched} of {expected} listings collected (limit {q.limit})")
        else:
            status, termination = "ok", "exhausted"
        rep = report(PROVIDER, started, status=status, termination=termination,
                     fetched=fetched, unique=len(items), pages=1, expected=expected,
                     warnings=warnings, finished_at=self._clock())
        return DiscoveryResult(items=items, run_report=rep, errors=list(rep.errors))

    def _record(self, row: dict[str, Any], source_id: str, q: LodgingQuery,
                collected_at: datetime, snapshot_id: str | None) -> SourceRecord:
        url = row.get("url")
        source_url = stay_url(url, q) if isinstance(url, str) and url.startswith("http") else None
        payload = {
            "search": row, "detail": None, "detail_collected_at": None,
            "query": _query_echo(q), "market_context": dict(MARKET_CONTEXT),
            "dataset_id": DATASET_BOOKING_SEARCH,
        }
        return SourceRecord(
            provider=PROVIDER, source_id=source_id, source_mode="live",
            collected_at=collected_at, source_url=source_url, request_id=snapshot_id,
            content_hash=content_hash(row), payload=payload,
        )

    async def verify(
        self, records: list[SourceRecord], q: LodgingQuery,
    ) -> tuple[list[SourceRecord], RunReport]:
        started = self._clock()
        top = [r for r in records[: q.verify_top] if r.source_url is not None]
        if not top:
            return records, report(VERIFY_PROVIDER, started, status="ok",
                                   termination="not_applicable", finished_at=self._clock())
        if not has_key(self._client):
            return records, missing_credentials_report(VERIFY_PROVIDER, started, KEY_NAME)
        inputs = [{"url": stay_url(str(r.source_url), q), "country": q.country} for r in top]
        try:
            got = await collect(self._client, DATASET_BOOKING_DETAIL, inputs, method=None,
                                limit_per_input=None, poll_interval=self._poll_interval,
                                max_wait=self._max_wait)
        except BrightDataError as exc:
            return records, self._failed(VERIFY_PROVIDER, started, exc)

        detail_at = self._clock().isoformat()
        by_id: dict[str, dict[str, Any]] = {}
        by_slug: dict[str, dict[str, Any]] = {}
        for row in got.rows:
            if row.get("listing_id") not in (None, ""):
                by_id.setdefault(str(row["listing_id"]), row)
            slug = _slug(row.get("url"))
            if slug:
                by_slug.setdefault(slug, row)
        wanted = {r.source_id for r in top}
        matched: set[str] = set()
        out: list[SourceRecord] = []
        for record in records:
            detail = None
            if record.source_id in wanted:
                detail = by_id.get(record.source_id) or by_slug.get(_slug(str(record.source_url)) or "")
            if detail is None:
                out.append(record)
                continue
            matched.add(record.source_id)
            payload = {**record.payload, "detail": detail, "detail_collected_at": detail_at}
            out.append(record.model_copy(update={"payload": payload}))
        warnings = list(got.warnings)
        if len(matched) < len(top):
            warnings.append(f"{len(top) - len(matched)} of {len(top)} listing(s) not verified")
        status = "ok" if len(matched) == len(top) else ("degraded" if matched else "failed")
        termination = "exhausted" if matched else "error"
        rep = report(VERIFY_PROVIDER, started, status=status, termination=termination,
                     fetched=len(got.rows), unique=len(matched), pages=1, expected=len(top),
                     warnings=warnings, finished_at=self._clock())
        return out, rep

    async def discover(self, query: DiscoveryQuery) -> DiscoveryResult:
        started = self._clock()
        try:
            q = LodgingQuery.from_discovery(query)
        except (ValueError, ValidationError) as exc:
            msg = f"invalid lodging query: {exc}".splitlines()[0]
            rep = report(PROVIDER, started, status="failed", termination="error",
                         errors=[msg], finished_at=self._clock())
            return DiscoveryResult(items=[], run_report=rep, errors=[msg])
        return await self.search(q)

    async def fetch_details(self, ref: SourceRef) -> SourceRecord:
        if ref.url is None:
            raise ValueError("booking fetch_details needs ref.url (hotel page with stay dates)")
        url = str(ref.url)
        params = parse_qs(urlsplit(url).query)
        if not params.get("checkin") or not params.get("checkout"):
            raise ValueError("booking fetch_details needs checkin and checkout in ref.url")
        if not has_key(self._client):
            raise BrightDataError(f"missing_credentials: {KEY_NAME}")
        got = await collect(self._client, DATASET_BOOKING_DETAIL,
                            [{"url": url, "country": MARKET_CONTEXT["country"]}], method=None,
                            limit_per_input=None, poll_interval=self._poll_interval,
                            max_wait=self._max_wait)
        if not got.rows:
            raise BrightDataError(f"Bright Data {DATASET_BOOKING_DETAIL}: no detail row")
        row = got.rows[0]
        collected_at = self._clock()
        query = {"check_in": params["checkin"][0], "check_out": params["checkout"][0]}
        for src, dst in (("group_adults", "adults"), ("no_rooms", "rooms"),
                         ("selected_currency", "currency")):
            if params.get(src):
                query[dst] = params[src][0]
        payload = {
            "search": None, "detail": row, "detail_collected_at": collected_at.isoformat(),
            "query": query, "market_context": dict(MARKET_CONTEXT),
            "dataset_id": DATASET_BOOKING_DETAIL,
        }
        return SourceRecord(
            provider=PROVIDER, source_id=ref.source_id, source_mode="live",
            collected_at=collected_at, source_url=url, request_id=got.snapshot_id,
            content_hash=content_hash(row), payload=payload,
        )


# ---------------------------------------------------------------- normalization


def _coords(value: Any) -> tuple[float | None, float | None]:
    if not isinstance(value, dict):
        return None, None
    lat = next((parse_float(value[k]) for k in ("lat", "latitude") if k in value), None)
    lng = next((parse_float(value[k]) for k in ("lng", "lon", "long", "longitude")
                if k in value), None)
    if lat is None or lng is None:
        return None, None
    return lat, lng


def _lodging_type(value: Any) -> str:
    text = str(value or "").lower()
    if "apartment" in text:
        return "apartment"
    if "hostel" in text:
        return "hostel"
    return "hotel"


def _search_quote(row: dict[str, Any]) -> PriceQuote:
    currency = row.get("currency")
    quote = PriceQuote(
        total=parse_money(row.get("final_price")),
        currency=currency.strip().upper() if isinstance(currency, str) and currency.strip() else None,
        kind="dated_total",
    )
    text = str(row.get("tax_description") or "").strip()
    low = text.lower()
    added = _ADDED_TAX_RE.search(text)
    if added:
        amount = parse_money(added.group("amount"))
        label = added.group("label").lower()
        quote.includes_all_fees = False
        if "fees" in label:
            quote.fees_total = amount
        else:
            quote.taxes = amount
    elif "includes taxes and fees" in low or "taxes and fees included" in low:
        quote.includes_all_fees = True
    if quote.total is None:
        quote.kind = "none"
    return quote


def _walk_dicts(value: Any, depth: int = 0) -> Iterator[dict[str, Any]]:
    if depth > 3:
        return
    if isinstance(value, dict):
        yield value
        for child in value.values():
            if isinstance(child, (list, dict)):
                yield from _walk_dicts(child, depth + 1)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_dicts(child, depth + 1)


def _texts(item: dict[str, Any]) -> str:
    return " ".join(v.lower() for v in item.values() if isinstance(v, str))


def _offer_price(item: dict[str, Any]) -> tuple[Decimal | None, str | None]:
    for key in _PRICE_KEYS:
        if key not in item:
            continue
        value = item[key]
        currency = item.get("currency")
        if isinstance(value, dict):
            currency = value.get("currency", currency)
            value = next((value[k] for k in ("amount", "value", "total") if k in value), None)
        amount = parse_money(value)
        if amount is not None:
            cur = currency.strip().upper() if isinstance(currency, str) and currency.strip() else None
            return amount, cur
    return None, None


def _taxes_included(item: dict[str, Any]) -> bool:
    if any(item.get(k) is True or parse_bool(item.get(k)) is True for k in _TAX_FLAG_KEYS):
        return True
    text = _texts(item)
    if "+" in text and "tax" in text:
        return False
    return any(signal in text for signal in _INCLUDED_TEXT)


def _offer_unavailable(item: dict[str, Any]) -> bool:
    for key in ("available", "is_available"):
        if key in item and parse_bool(item[key]) is False:
            return True
    text = _texts(item)
    return any(signal in text for signal in _UNAVAILABLE_TEXT)


def _detail_offers(detail: dict[str, Any], fallback_currency: str | None
                   ) -> list[tuple[Decimal, str | None]]:
    offers = []
    for item in _walk_dicts(detail.get("pricing")):
        amount, currency = _offer_price(item)
        if amount is None or _offer_unavailable(item):
            continue
        text = _texts(item)
        if "per night" in text or "/night" in text:
            continue
        if _taxes_included(item):
            offers.append((amount, currency or fallback_currency))
    return offers


def _detail_availability(detail: dict[str, Any]) -> str:
    value = detail.get("availability", None)
    if isinstance(value, str):
        low = value.lower()
        return "unavailable" if any(s in low for s in _UNAVAILABLE_TEXT) else "unknown"
    if not isinstance(value, list):
        return "unknown"
    if not value:
        return "unavailable"
    rooms = [item for item in value if isinstance(item, (dict, str))]
    if not rooms:
        return "unknown"
    for item in rooms:
        if isinstance(item, str):
            if not any(s in item.lower() for s in _UNAVAILABLE_TEXT):
                return "verified_available"
        elif not _offer_unavailable(item):
            return "verified_available"
    return "unavailable"


def to_lodging(
    record: SourceRecord, query: LodgingQuery, *, warnings: list[str] | None = None,
    now: datetime | None = None,
) -> Lodging | None:
    sink = warnings if warnings is not None else []
    payload = record.payload or {}
    search = payload.get("search") if isinstance(payload.get("search"), dict) else {}
    detail = payload.get("detail") if isinstance(payload.get("detail"), dict) else None
    title = search.get("title") or (detail or {}).get("title")
    if not isinstance(title, str) or not title.strip():
        return None

    quote = _search_quote(search) if search else PriceQuote()
    availability = "unknown"
    lat, lng = _coords(search.get("map_coordinates"))
    address = search.get("address") or None
    city = search.get("city") or None
    rating = parse_float(search.get("review_score"))
    rating_count = parse_int(search.get("review_count"))
    extra: list[SourceEvidence] = []

    if detail is not None:
        detail_at = _parse_dt(payload.get("detail_collected_at"))
        d_lat, d_lng = _coords(detail.get("coordinates"))
        if d_lat is not None:
            lat, lng = d_lat, d_lng
        address = detail.get("full_address") or detail.get("location") or address
        city = detail.get("city") or city
        if rating is None:
            rating = parse_float(detail.get("review_score"))
        if rating_count is None:
            rating_count = parse_int(detail.get("number_of_reviews"))
        d_in, d_out = parse_date(detail.get("check_in")), parse_date(detail.get("check_out"))
        if d_in == query.check_in and d_out == query.check_out:
            availability = _detail_availability(detail)
            offers = _detail_offers(detail, quote.currency)
            if offers and availability != "unavailable":
                total, currency = min(offers, key=lambda o: o[0])
                quote = PriceQuote(total=total, currency=currency, includes_all_fees=True,
                                   kind="verified", verified_at=detail_at)
        else:
            sink.append(f"{PROVIDER}:{record.source_id}: detail stay {d_in}..{d_out} does not "
                        "match query; detail price and availability ignored")
        extra.append(SourceEvidence(
            provider=PROVIDER, source_mode=record.source_mode, collected_at=detail_at,
            source_url=record.source_url, raw_ref=DATASET_BOOKING_DETAIL,
            source_record_id=record.source_id,
        ))

    if rating is not None and rating <= 0:
        rating = None
    return build_lodging(
        record, query, name=title.strip(), quote=quote,
        lodging_type=_lodging_type(search.get("property_type") or (detail or {}).get("property_type")),
        availability=availability, lat=lat, lng=lng,
        coordinate_precision="exact" if lat is not None else "unknown",
        address=address if isinstance(address, str) else None,
        city=city if isinstance(city, str) else None,
        free_cancellation=parse_bool(search.get("free_cancellation")),
        rating=rating, rating_scale=10 if rating is not None else None,
        rating_count=rating_count, booking_url=str(record.source_url) if record.source_url else None,
        echoed_check_in=parse_date(search.get("check_in")),
        echoed_check_out=parse_date(search.get("check_out")),
        echoed_adults=parse_int(search.get("adults")),
        extra_evidence=extra, warnings=sink, now=now,
    )
