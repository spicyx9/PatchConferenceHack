"""Airbnb stays: pyairbnb (primary) with Bright Data ``gd_ld7ll037kqy322v05`` as fallback.

Field facts come from real captures (raw/lodging/pyairbnb-*.json, pyairbnb 2.2.2, Fort Mason
bbox, 2026-10-27..30, 1 adult, USD) and the Bright Data catalogue + public sample:

- pyairbnb search rows: ``price.total.amount`` is always ``0`` and is never read. The stay
  price lives in ``price.break_down`` (``"3 nights x $143.65"``, ``"Resort fee"``, discount
  lines with negative amounts, and a summary line ``"Price after discount"`` that repeats the
  sum and is therefore skipped). ``coordinates.longitud`` (sic) is approximate.
- ``get_price`` returns ``main.price`` / ``main.discountedPrice`` with a nights qualifier;
  ``get_calendar`` returns months of days with ``available``, ``availableForCheckin``,
  ``availableForCheckout``, ``minNights`` and ``maxNights``.
- Bright Data rows: ``total_price`` and ``price`` were null in the public sample; dates are
  echoed in ``travel_details``. A total is only trusted when that echo equals the query.

Airbnb never reaches ``verified_bookable`` through this adapter: taxes are never exposed by
search nor by ``get_price``, so ``includes_all_fees`` stays ``None`` and the best status is
``quoted_total`` (with ``availability=verified_available`` after a calendar check).

Fallback to Bright Data happens only on schema error, block, timeout, missing dependency or
price fields absent on every row. Zero results is a real (degraded) answer, not a fallback.
"""

from __future__ import annotations

import asyncio
import importlib
import re
from collections.abc import Callable
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Protocol
from urllib.parse import urlencode

from conferge.core.brightdata import BrightDataClient, BrightDataError
from conferge.core.schemas import (
    DiscoveryQuery,
    DiscoveryResult,
    Lodging,
    RunReport,
    SourceRecord,
    SourceRef,
    Termination,
)
from conferge.lodging._bd import SnapshotPending, collect, has_key
from conferge.lodging._common import (
    AIRBNB,
    DATASET_AIRBNB,
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

PROVIDER = AIRBNB
MAX_VERIFY = 10
RATING_SCALE = 5

# Error markers (prefix of run_report.errors entries) that make AirbnbSource switch backend.
DEPENDENCY_MISSING = "dependency_missing"
SCHEMA_CHANGED = "schema_changed"
BLOCKED = "blocked"
TIMEOUT = "timeout"
PRICE_ABSENT = "price_fields_absent"
FALLBACK_MARKERS = (DEPENDENCY_MISSING, SCHEMA_CHANGED, BLOCKED, TIMEOUT, PRICE_ABSENT)

_NIGHTS_LINE = re.compile(r"(\d+)\s+nights?\s+x", re.IGNORECASE)
_QUALIFIER = re.compile(r"for\s+(\d+)\s+nights?", re.IGNORECASE)
_SUMMARY_LINE = re.compile(r"^\s*(price after|total)", re.IGNORECASE)
_AT_PROPERTY = re.compile(r"(payable|pay|due)\s+at\s+(the\s+)?property", re.IGNORECASE)
_BLOCK_HINTS = re.compile(r"\b(403|429|captcha|blocked|forbidden|too many requests)\b",
                          re.IGNORECASE)
# Bright Data row fields too heavy to keep in a payload (CLAUDE.md rule 7).
_BD_HEAVY = {"reviews", "description", "description_html", "description_by_sections",
             "location_details_html", "reviews_details", "images", "amenities", "host_image",
             "image", "house_rules", "highlights", "category_rating", "available_dates"}

Clock = Callable[[], datetime]


class AirbnbError(RuntimeError):
    """Airbnb detail fetch failed (message never contains credentials)."""


def room_url(room_id: str, q: LodgingQuery) -> str:
    params = {"check_in": q.check_in.isoformat(), "check_out": q.check_out.isoformat(),
              "adults": q.adults, "currency": q.currency}
    return f"https://www.airbnb.com/rooms/{room_id}?{urlencode(params)}"


def _query_echo(q: LodgingQuery, **extra: Any) -> dict[str, Any]:
    return {"check_in": q.check_in.isoformat(), "check_out": q.check_out.isoformat(),
            "adults": q.adults, "currency": q.currency, **extra}


def _payload(backend: str, row: dict[str, Any], q: LodgingQuery, **extra: Any) -> dict[str, Any]:
    return {"backend": backend, "search": row, "price_check": None, "price_checked_at": None,
            "calendar": None, "calendar_checked_at": None, "query": _query_echo(q, **extra),
            "market_context": dict(MARKET_CONTEXT)}


def _failed(started: datetime, marker: str, detail: str, termination: Termination = "error",
            *, warnings: list[str] | None = None) -> DiscoveryResult:
    message = f"{marker}: {detail}"
    return DiscoveryResult(
        items=[], errors=[message],
        run_report=report(PROVIDER, started, status="failed", termination=termination,
                          errors=[message], warnings=warnings),
    )


def _classify_exception(exc: BaseException) -> tuple[str, Termination]:
    text = f"{type(exc).__name__}: {exc}"
    if _BLOCK_HINTS.search(text):
        return BLOCKED, "rate_limited" if "429" in text else "blocked"
    return "error", "error"


def _dedupe_truncate(
    rows: list[tuple[str, dict[str, Any]]], limit: int, warnings: list[str], label: str,
) -> list[tuple[str, dict[str, Any]]]:
    seen: dict[str, dict[str, Any]] = {}
    for key, row in rows:
        seen.setdefault(key, row)
    unique = list(seen.items())
    if len(unique) < len(rows):
        warnings.append(f"{label}: {len(rows) - len(unique)} duplicate listing(s) merged")
    if len(unique) > limit:
        warnings.append(f"{label}: kept {limit} of {len(unique)} unique listings (query limit)")
    return unique[:limit]


def _has_search_price(row: dict[str, Any]) -> bool:
    price = row.get("price")
    if not isinstance(price, dict):
        return False
    lines = price.get("break_down")
    if isinstance(lines, list) and any(
        isinstance(line, dict) and parse_money(line.get("amount")) for line in lines
    ):
        return True
    unit = price.get("unit")
    return isinstance(unit, dict) and parse_money(unit.get("amount")) is not None


class AirbnbBackend(Protocol):
    name: str

    async def search(self, q: LodgingQuery) -> DiscoveryResult: ...

    async def enrich(
        self, records: list[SourceRecord], q: LodgingQuery,
    ) -> tuple[list[SourceRecord], list[str]]: ...


class PyAirbnbBackend:
    """pyairbnb (synchronous, curl_cffi) called through threads with a hard timeout."""

    name = "pyairbnb"

    def __init__(self, module: Any | None = None, *, timeout: float = 60.0,
                 clock: Clock = now_utc, zoom: int = 14) -> None:
        self._module = module
        self.timeout = timeout
        self.clock = clock
        self.zoom = zoom

    def _load(self) -> Any:
        if self._module is None:
            self._module = importlib.import_module("pyairbnb")  # pinned in pyproject; still guarded
        return self._module

    async def _call(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        return await asyncio.wait_for(asyncio.to_thread(fn, *args, **kwargs), self.timeout)

    async def search(self, q: LodgingQuery) -> DiscoveryResult:
        started = self.clock()
        try:
            mod = self._load()
        except ImportError:
            return _failed(started, DEPENDENCY_MISSING, "pyairbnb")
        ne_lat, ne_lng, sw_lat, sw_lng = q.bounding_box()
        try:
            rows = await self._call(
                mod.search_all, q.check_in.isoformat(), q.check_out.isoformat(),
                ne_lat, ne_lng, sw_lat, sw_lng, self.zoom, 0, 0,
                adults=q.adults, currency=q.currency,
            )
        except (asyncio.TimeoutError, TimeoutError):
            return _failed(started, TIMEOUT, f"pyairbnb search_all exceeded {self.timeout}s")
        except Exception as exc:  # noqa: BLE001 - provider errors are reported, not raised
            marker, termination = _classify_exception(exc)
            return _failed(started, marker, f"pyairbnb search_all {type(exc).__name__}",
                           termination)
        if not isinstance(rows, list):
            return _failed(started, SCHEMA_CHANGED,
                           f"search_all returned {type(rows).__name__}, expected list",
                           "schema_changed")
        warnings: list[str] = []
        valid = [r for r in rows if isinstance(r, dict) and r.get("room_id") not in (None, "")
                 and "price" in r]
        if rows and not valid:
            return _failed(started, SCHEMA_CHANGED,
                           f"none of {len(rows)} rows has room_id and price", "schema_changed")
        if len(valid) < len(rows):
            warnings.append(f"pyairbnb: {len(rows) - len(valid)} row(s) without room_id/price "
                            "excluded")
        if not valid:
            warnings.append("pyairbnb: zero results for the bounding box and stay")
            return DiscoveryResult(items=[], run_report=report(
                PROVIDER, started, status="degraded", termination="error", warnings=warnings,
                finished_at=self.clock()))
        if not any(_has_search_price(r) for r in valid):
            return _failed(started, PRICE_ABSENT,
                           f"no price.break_down or unit.amount on any of {len(valid)} rows",
                           "schema_changed", warnings=warnings)
        kept = _dedupe_truncate([(str(r["room_id"]), r) for r in valid], q.limit, warnings,
                                "pyairbnb")
        collected = self.clock()
        bbox = [round(v, 6) for v in (ne_lat, ne_lng, sw_lat, sw_lng)]
        items = [
            SourceRecord(
                provider=PROVIDER, source_id=room_id, source_mode="live", collected_at=collected,
                source_url=room_url(room_id, q), request_id=None, content_hash=content_hash(row),
                payload=_payload(self.name, row, q, bbox=bbox, zoom=self.zoom),
            )
            for room_id, row in kept
        ]
        unique = len({str(r["room_id"]) for r in valid})
        return DiscoveryResult(items=items, run_report=report(
            PROVIDER, started, status="ok", termination="exhausted", fetched=len(valid),
            unique=unique, warnings=warnings, finished_at=self.clock()))

    async def enrich(
        self, records: list[SourceRecord], q: LodgingQuery,
    ) -> tuple[list[SourceRecord], list[str]]:
        warnings: list[str] = []
        top = min(q.verify_top, MAX_VERIFY)
        targets = [i for i, r in enumerate(records)
                   if r.payload.get("backend") == self.name][:top]
        if not targets:
            return list(records), warnings
        try:
            mod = self._load()
        except ImportError:
            return list(records), [f"{DEPENDENCY_MISSING}: pyairbnb; Airbnb records not verified"]
        api_key: str | None = None
        try:
            api_key = await self._call(mod.get_api_key, "")
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"pyairbnb get_api_key failed ({type(exc).__name__}); "
                            "calendar checks skipped")
        out = list(records)
        sem = asyncio.Semaphore(3)

        async def one(index: int) -> None:
            async with sem:
                out[index] = await self._enrich_one(mod, out[index], q, api_key, warnings)

        await asyncio.gather(*(one(i) for i in targets))
        return out, warnings

    async def _enrich_one(self, mod: Any, record: SourceRecord, q: LodgingQuery,
                          api_key: str | None, warnings: list[str]) -> SourceRecord:
        payload = dict(record.payload)
        rid = record.source_id
        try:
            res = await self._call(mod.get_price, rid, q.check_in, q.check_out,
                                   adults=q.adults, currency=q.currency)
            main = res.get("main") if isinstance(res, dict) else None
            if isinstance(main, dict):
                payload["price_check"] = {"main": main}
                payload["price_checked_at"] = self.clock().isoformat()
            else:
                warnings.append(f"airbnb:{rid}: get_price returned no main block")
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"airbnb:{rid}: get_price failed ({type(exc).__name__})")
        if api_key is not None:
            try:
                months = await self._call(mod.get_calendar, api_key=api_key, room_id=rid)
                days = _stay_days(months, q)
                if days is None:
                    warnings.append(f"airbnb:{rid}: calendar payload not a month list")
                else:
                    payload["calendar"] = days
                    payload["calendar_checked_at"] = self.clock().isoformat()
            except Exception as exc:  # noqa: BLE001
                warnings.append(f"airbnb:{rid}: get_calendar failed ({type(exc).__name__})")
        return record.model_copy(update={"payload": payload})

    async def get_details(self, room_id: str) -> dict[str, Any]:
        try:
            mod = self._load()
        except ImportError as exc:
            raise AirbnbError(f"{DEPENDENCY_MISSING}: pyairbnb") from exc
        try:
            data = await self._call(mod.get_details, room_id=int(room_id), currency="USD")
        except (asyncio.TimeoutError, TimeoutError) as exc:
            raise AirbnbError(f"{TIMEOUT}: pyairbnb get_details exceeded {self.timeout}s") from exc
        except Exception as exc:  # noqa: BLE001
            raise AirbnbError(f"pyairbnb get_details failed ({type(exc).__name__})") from exc
        if not isinstance(data, dict) or not data:
            raise AirbnbError(f"{SCHEMA_CHANGED}: get_details returned no object")
        return data


def _stay_days(months: Any, q: LodgingQuery) -> list[dict[str, Any]] | None:
    """Keep only calendar days check_in..check_out (inclusive)."""
    if not isinstance(months, list):
        return None
    lo, hi = q.check_in.isoformat(), q.check_out.isoformat()
    keep = ("calendarDate", "available", "availableForCheckin", "availableForCheckout",
            "minNights", "maxNights")
    days = []
    for month in months:
        for day in (month.get("days") or []) if isinstance(month, dict) else []:
            if isinstance(day, dict) and lo <= str(day.get("calendarDate", "")) <= hi:
                days.append({k: day.get(k) for k in keep if k in day})
    return sorted(days, key=lambda d: d["calendarDate"])


class BrightDataAirbnbBackend:
    """Bright Data Airbnb dataset, ``discover_by_location``."""

    name = "brightdata"

    def __init__(self, client: BrightDataClient | None = None, *, poll_interval: float = 5.0,
                 max_wait: float = 240.0, clock: Clock = now_utc) -> None:
        self._client = client
        self._owns_client = client is None
        self.poll_interval = poll_interval
        self.max_wait = max_wait
        self.clock = clock

    @property
    def client(self) -> BrightDataClient:
        if self._client is None:
            self._client = BrightDataClient.from_env()
        return self._client

    async def aclose(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()

    @staticmethod
    def inputs(q: LodgingQuery) -> list[dict[str, Any]]:
        iso = "T00:00:00.000Z"
        return [{"location": q.location, "check_in": q.check_in.isoformat() + iso,
                 "check_out": q.check_out.isoformat() + iso, "num_of_adults": q.adults,
                 "currency": q.currency, "country": q.country}]

    async def search(self, q: LodgingQuery) -> DiscoveryResult:
        started = self.clock()
        if not has_key(self.client):
            rep = missing_credentials_report(PROVIDER, started, "BRIGHTDATA_API_KEY not set")
            return DiscoveryResult(items=[], run_report=rep, errors=list(rep.errors))
        try:
            got = await collect(self.client, DATASET_AIRBNB, self.inputs(q),
                                method="discover_by_location", limit_per_input=q.limit,
                                poll_interval=self.poll_interval, max_wait=self.max_wait)
        except SnapshotPending as exc:
            msg = f"snapshot_pending: {exc.snapshot_id} still running after {self.max_wait}s"
            return DiscoveryResult(items=[], errors=[msg], run_report=report(
                PROVIDER, started, status="failed", termination="error", errors=[msg]))
        except BrightDataError as exc:
            marker, termination = _classify_exception(exc)
            msg = f"{marker}: {exc}" if marker != "error" else str(exc)
            return DiscoveryResult(items=[], errors=[msg], run_report=report(
                PROVIDER, started, status="failed", termination=termination, errors=[msg]))
        warnings = list(got.warnings)
        rows = [r for r in got.rows if r.get("property_id") not in (None, "")]
        if len(rows) < len(got.rows):
            warnings.append(f"brightdata: {len(got.rows) - len(rows)} row(s) without "
                            "property_id excluded")
        if not rows:
            warnings.append("brightdata: zero results for the location and stay")
            return DiscoveryResult(items=[], run_report=report(
                PROVIDER, started, status="degraded", termination="error",
                fetched=0, warnings=warnings, finished_at=self.clock()))
        kept = _dedupe_truncate([(str(r["property_id"]), r) for r in rows], q.limit, warnings,
                                "brightdata")
        collected = self.clock()
        items = []
        for pid, row in kept:
            slim = {k: v for k, v in row.items() if k not in _BD_HEAVY}
            items.append(SourceRecord(
                provider=PROVIDER, source_id=pid, source_mode="live", collected_at=collected,
                source_url=room_url(pid, q), request_id=got.snapshot_id,
                content_hash=content_hash(row),
                payload=_payload(self.name, slim, q, dataset=DATASET_AIRBNB, location=q.location),
            ))
        status = "degraded" if got.error_rows else "ok"
        return DiscoveryResult(items=items, run_report=report(
            PROVIDER, started, status=status, termination="exhausted", fetched=len(rows),
            unique=len({str(r["property_id"]) for r in rows}), warnings=warnings,
            finished_at=self.clock()))

    async def enrich(
        self, records: list[SourceRecord], q: LodgingQuery,
    ) -> tuple[list[SourceRecord], list[str]]:
        return list(records), []


class AirbnbSource:
    """Airbnb stays behind one interface: primary backend, fallback on hard failures only."""

    provider = PROVIDER

    def __init__(self, primary: AirbnbBackend | None = None,
                 fallback: AirbnbBackend | None = None, *, clock: Clock = now_utc) -> None:
        self.primary: AirbnbBackend = primary or PyAirbnbBackend(clock=clock)
        self.fallback: AirbnbBackend | None = (
            fallback if fallback is not None else BrightDataAirbnbBackend(clock=clock))
        self.clock = clock

    async def aclose(self) -> None:
        for backend in (self.primary, self.fallback):
            closer = getattr(backend, "aclose", None)
            if closer is not None:
                await closer()

    @staticmethod
    def needs_fallback(result: DiscoveryResult) -> bool:
        errors = [*result.run_report.errors, *result.errors]
        return any(e.startswith(FALLBACK_MARKERS) for e in errors)

    async def search(self, q: LodgingQuery) -> DiscoveryResult:
        first = await self.primary.search(q)
        if not self.needs_fallback(first) or self.fallback is None:
            return first
        primary_errors = list(dict.fromkeys([*first.run_report.errors, *first.errors]))
        switch = (f"airbnb: primary {self.primary.name} failed "
                  f"({'; '.join(primary_errors)}); switched to {self.fallback.name}")
        second = await self.fallback.search(q)
        rep = second.run_report
        merged = rep.model_copy(update={
            "provider": PROVIDER,
            "warnings": [switch, *(f"primary {self.primary.name}: {w}"
                                   for w in first.run_report.warnings), *rep.warnings],
        })
        return DiscoveryResult(items=second.items, run_report=RunReport.model_validate(
            merged.model_dump()), errors=second.errors)

    def _backends(self) -> dict[str, AirbnbBackend]:
        found = {self.primary.name: self.primary}
        if self.fallback is not None:
            found.setdefault(self.fallback.name, self.fallback)
        return found

    async def verify(
        self, records: list[SourceRecord], q: LodgingQuery,
    ) -> tuple[list[SourceRecord], RunReport]:
        started = self.clock()
        warnings: list[str] = []
        backends = self._backends()
        out = list(records)
        groups: dict[str, list[int]] = {}
        for i, rec in enumerate(records):
            groups.setdefault(str(rec.payload.get("backend")), []).append(i)
        for name, indexes in groups.items():
            backend = backends.get(name)
            if backend is None:
                warnings.append(f"airbnb: no backend {name!r} to verify {len(indexes)} record(s)")
                continue
            enriched, notes = await backend.enrich([records[i] for i in indexes], q)
            warnings.extend(notes)
            for i, rec in zip(indexes, enriched, strict=True):
                out[i] = rec
        rep = report(PROVIDER, started, status="degraded" if warnings else "ok",
                     termination="not_applicable", fetched=len(records), unique=len(records),
                     warnings=warnings, finished_at=self.clock())
        return out, rep

    async def discover(self, query: DiscoveryQuery) -> DiscoveryResult:
        started = self.clock()
        try:
            q = LodgingQuery.from_discovery(query)
        except ValueError as exc:
            msg = f"invalid_query: {exc}"
            return DiscoveryResult(items=[], errors=[msg], run_report=report(
                PROVIDER, started, status="failed", termination="error", errors=[msg]))
        return await self.search(q)

    async def fetch_details(self, ref: SourceRef) -> SourceRecord:
        if ref.provider != PROVIDER or not ref.source_id.isdigit():
            raise AirbnbError(f"not an Airbnb room id: {ref.provider}:{ref.source_id}")
        backend = self.primary if isinstance(self.primary, PyAirbnbBackend) else PyAirbnbBackend(
            clock=self.clock)
        data = await backend.get_details(ref.source_id)
        return SourceRecord(
            provider=PROVIDER, source_id=ref.source_id, source_mode="live",
            collected_at=self.clock(),
            source_url=f"https://www.airbnb.com/rooms/{ref.source_id}",
            content_hash=content_hash(data),
            payload={"backend": backend.name, "details": data,
                     "market_context": dict(MARKET_CONTEXT)},
        )


# ---------------------------------------------------------------- normalization


def _signed(value: Any) -> Decimal | None:
    if isinstance(value, bool) or not isinstance(value, (int, float, str, Decimal)):
        return None
    try:
        amount = Decimal(str(value).replace("$", "").replace(",", "").strip())
    except ArithmeticError:
        return None
    return amount if amount.is_finite() else None


def search_quote(row: dict[str, Any], query: LodgingQuery, currency: str,
                 warnings: list[str], label: str) -> PriceQuote:
    """Stay quote from a pyairbnb search row (``price.total.amount`` is ignored: always 0)."""
    none = PriceQuote(currency=currency)
    price = row.get("price") if isinstance(row.get("price"), dict) else {}
    lines = [ln for ln in (price.get("break_down") or []) if isinstance(ln, dict)]
    nights_lines = [(ln, _NIGHTS_LINE.search(str(ln.get("description", "")))) for ln in lines]
    nights_lines = [(ln, m) for ln, m in nights_lines if m]
    if nights_lines:
        line, match = nights_lines[0]
        n = int(match.group(1))
        if n != query.nights:
            warnings.append(f"{label}: break_down covers {n} nights, query has {query.nights}; "
                            "price dropped")
            return none
        base = parse_money(line.get("amount"))
        if base is None:
            return none
        total = base
        fees = Decimal(0)
        at_property = Decimal(0)
        for ln in lines:
            if ln is line or _SUMMARY_LINE.search(str(ln.get("description", ""))):
                continue
            amount = _signed(ln.get("amount"))
            if amount is None or amount == 0:
                continue
            if amount > 0 and _AT_PROPERTY.search(str(ln.get("description", ""))):
                at_property += amount
                continue
            total += amount
            if amount > 0:
                fees += amount
        if total <= 0:
            return none
        return PriceQuote(total=total, base_total=base, fees_total=fees or None,
                          payable_at_property=at_property or None, currency=currency,
                          includes_all_fees=None, kind="dated_total")
    unit = price.get("unit") if isinstance(price.get("unit"), dict) else {}
    qual = _QUALIFIER.search(str(unit.get("qualifier") or ""))
    if qual:
        n = int(qual.group(1))
        if n != query.nights:
            warnings.append(f"{label}: unit price is for {n} nights, query has {query.nights}; "
                            "price dropped")
            return none
        # ``unit.discount`` (when present) is the discounted stay price actually charged;
        # ``unit.amount`` is then the pre-discount price (capture: 349 vs 292 = get_price).
        total = parse_money(unit.get("discount")) or parse_money(unit.get("amount"))
        if total is not None:
            return PriceQuote(total=total, currency=currency, kind="dated_total")
    return none


def _price_check_quote(check: Any, query: LodgingQuery, currency: str, warnings: list[str],
                       label: str) -> PriceQuote | None:
    main = check.get("main") if isinstance(check, dict) else None
    if not isinstance(main, dict):
        return None
    qual = _QUALIFIER.search(str(main.get("qualifier") or ""))
    if not qual:
        warnings.append(f"{label}: get_price without nights qualifier; ignored")
        return None
    if int(qual.group(1)) != query.nights:
        warnings.append(f"{label}: get_price is for {qual.group(1)} nights, query has "
                        f"{query.nights}; ignored")
        return None
    total = parse_money(main.get("discountedPrice")) or parse_money(main.get("price"))
    if total is None:
        return None
    base = None
    details = main.get("details")
    if isinstance(details, dict):
        for desc, amount in details.items():
            if _NIGHTS_LINE.search(str(desc)):
                base = parse_money(amount)
                break
    return PriceQuote(total=total, base_total=base, currency=currency, kind="dated_total")


def calendar_availability(days: Any, query: LodgingQuery) -> str:
    if not isinstance(days, list) or not days:
        return "unknown"
    by_date = {str(d.get("calendarDate")): d for d in days if isinstance(d, dict)}
    nights = [(query.check_in + timedelta(days=i)).isoformat() for i in range(query.nights)]
    if any(by_date.get(n, {}).get("available") is False for n in nights):
        return "unavailable"
    if not all(by_date.get(n, {}).get("available") is True for n in nights):
        return "unknown"
    first = by_date[query.check_in.isoformat()]
    if first.get("availableForCheckin") is not True:
        return "unknown"
    min_n, max_n = parse_int(first.get("minNights")), parse_int(first.get("maxNights"))
    if min_n is None or min_n > query.nights:
        return "unknown"
    if max_n is not None and max_n < query.nights:
        return "unknown"
    out = by_date.get(query.check_out.isoformat())
    if out is not None and out.get("availableForCheckout") is False:
        return "unknown"
    return "verified_available"


def _lodging_type(name: str, badges: Any) -> str:
    low = name.lower()
    if "dorm" in low or "hostel" in low:
        return "hostel"
    if (isinstance(badges, list) and "FEATURED_HOTEL" in badges) or "hotel" in low:
        return "hotel"
    return "apartment"


def _free_cancellation(messages: Any) -> bool | None:
    for msg in messages if isinstance(messages, list) else []:
        text = msg.get("text") if isinstance(msg, dict) else msg
        if isinstance(text, str) and "free cancellation" in text.lower():
            return True
    return None


def _parse_ts(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def _echo(payload: dict[str, Any]) -> tuple[date | None, date | None, int | None]:
    echo = payload.get("query") if isinstance(payload.get("query"), dict) else {}
    return parse_date(echo.get("check_in")), parse_date(echo.get("check_out")), \
        parse_int(echo.get("adults"))


def _rating(value: Any) -> float | None:
    rating = parse_float(value)
    return rating if rating is not None and 0 < rating <= RATING_SCALE else None


def _pyairbnb_lodging(record: SourceRecord, query: LodgingQuery, row: dict[str, Any],
                      sink: list[str], now: datetime | None) -> Lodging:
    payload = record.payload
    label = f"airbnb:{record.source_id}"
    currency = str((payload.get("query") or {}).get("currency") or query.currency)
    name = str(row.get("name") or row.get("title") or f"Airbnb {record.source_id}")
    quote = search_quote(row, query, currency, sink, label)
    checked_at = _parse_ts(payload.get("price_checked_at"))
    if payload.get("price_check") and checked_at is not None and checked_at >= record.collected_at:
        checked = _price_check_quote(payload["price_check"], query, currency, sink, label)
        if checked is not None:
            if quote.total is not None and checked.total != quote.total:
                sink.append(f"{label}: get_price total {checked.total} differs from search "
                            f"{quote.total}; using get_price")
            quote = checked
    coords = row.get("coordinates") if isinstance(row.get("coordinates"), dict) else {}
    lat = parse_float(coords.get("latitude"))
    lng = parse_float(coords.get("longitud", coords.get("longitude")))
    rating = row.get("rating") if isinstance(row.get("rating"), dict) else {}
    value = _rating(rating.get("value"))
    in_, out_, adults = _echo(payload)
    return build_lodging(
        record, query, name=name, quote=quote,
        lodging_type=_lodging_type(f"{name} {row.get('title') or ''}", row.get("badges")),
        availability=calendar_availability(payload.get("calendar"), query),
        lat=lat, lng=lng, coordinate_precision="approximate",
        free_cancellation=_free_cancellation(row.get("paymentMessages")),
        rating=value, rating_scale=RATING_SCALE,
        rating_count=parse_int(rating.get("reviewCount")) if value is not None else None,
        booking_url=room_url(record.source_id, query),
        echoed_check_in=in_, echoed_check_out=out_, echoed_adults=adults,
        warnings=sink, now=now,
    )


def _brightdata_lodging(record: SourceRecord, query: LodgingQuery, row: dict[str, Any],
                        sink: list[str], now: datetime | None) -> Lodging:
    label = f"airbnb:{record.source_id}"
    currency = str(row.get("currency") or query.currency)
    name = str(row.get("listing_title") or row.get("name") or row.get("listing_name")
               or f"Airbnb {record.source_id}")
    travel = row.get("travel_details") if isinstance(row.get("travel_details"), dict) else {}
    d_in, d_out = parse_date(travel.get("check_in")), parse_date(travel.get("check_out"))
    adults = parse_int(travel.get("num_of_adults"))
    dates_echoed = d_in == query.check_in and d_out == query.check_out
    quote = PriceQuote(currency=currency)
    total = parse_money(row.get("total_price"))
    nightly = parse_money(row.get("price"))
    if total is not None and dates_echoed:
        quote = PriceQuote(total=total, currency=currency, kind="dated_total")
    else:
        if total is not None:
            sink.append(f"{label}: total_price without dates echo for this stay; not used")
        if nightly is not None:
            quote = PriceQuote(nightly_rate=nightly, currency=currency, kind="from_price")
    availability = "unknown"
    if parse_bool(row.get("availability")) is False and dates_echoed:
        availability = "unavailable"
    kind_text = f"{row.get('listing_name') or ''} {name}"
    value = _rating(row.get("ratings"))
    return build_lodging(
        record, query, name=name, quote=quote, lodging_type=_lodging_type(kind_text, None),
        availability=availability, lat=parse_float(row.get("lat")),
        lng=parse_float(row.get("long")),
        coordinate_precision="exact" if row.get("is_exact_location") is True else "approximate",
        city=row.get("location") if isinstance(row.get("location"), str) else None,
        free_cancellation=True if "free cancellation" in str(
            row.get("cancellation_policy") or "").lower() else None,
        rating=value, rating_scale=RATING_SCALE,
        rating_count=parse_int(row.get("property_number_of_reviews")) if value else None,
        booking_url=room_url(record.source_id, query),
        echoed_check_in=d_in, echoed_check_out=d_out, echoed_adults=adults,
        warnings=sink, now=now,
    )


def to_lodging(record: SourceRecord, query: LodgingQuery, *, warnings: list[str] | None = None,
               now: datetime | None = None) -> Lodging | None:
    sink = warnings if warnings is not None else []
    row = record.payload.get("search")
    if record.provider != PROVIDER or not isinstance(row, dict) or not record.source_id:
        return None
    backend = record.payload.get("backend")
    if backend == "pyairbnb":
        return _pyairbnb_lodging(record, query, row, sink, now)
    if backend == "brightdata":
        return _brightdata_lodging(record, query, row, sink, now)
    sink.append(f"airbnb:{record.source_id}: unknown backend {backend!r}")
    return None
