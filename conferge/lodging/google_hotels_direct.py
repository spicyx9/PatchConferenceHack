"""Google Hotels without a key: one server-rendered search page, read like swoop-hotels does.

Method taken from gobeyondpty/swoop-hotels (MIT), reimplemented, not copied: GET
``https://www.google.com/travel/search?q=..&check_in_date=..&check_out_date=..&adults=..
&currency=..`` with a browser TLS fingerprint (primp), then parse the
``AF_initDataCallback`` blocks. A block is used only when its context echoes the requested
dates and currency. Hotel records: ``[1]`` name, ``[2][0]`` (lat, lng), ``[2][1][0][0][0]``
address, ``[6][2][1]`` nightly price block, ``[6][2][9|17|8]`` stay total block,
``[7][0]`` rating and review count, ``[9]`` entity id. One attempt, 20 s timeout, at most
15 hotels. A stay total shown on the page is ``quoted_total``; a nightly price alone is
``indicative``; no price stays null. Secondary source: shown after the Bright Data
datasets (provenance tier), never instead of them.
"""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Callable
from datetime import datetime
from decimal import Decimal
from typing import Any
from urllib.parse import urlencode

from conferge.core.schemas import DiscoveryResult, Lodging, SourceRecord, SourceRef
from conferge.lodging._common import content_hash, now_utc, report
from conferge.lodging.models import LodgingQuery
from conferge.lodging.normalize import PriceQuote, build_lodging

PROVIDER = "google_hotels_direct"
PAGE_URL = "https://www.google.com/travel/search"
TIMEOUT = 20.0
MAX_HOTELS = 15
Fetch = Callable[[str, float], str]
_AF = re.compile(r"AF_initDataCallback\(\{key:\s*['\"]([^'\"]+)['\"].*?\bdata\s*:", re.S)


def _get(data: Any, path: list[int], default: Any = None) -> Any:
    for key in path:
        if not isinstance(data, list) or not -len(data) <= key < len(data):
            return default
        data = data[key]
    return data


def search_url(q: LodgingQuery) -> str:
    return f"{PAGE_URL}?" + urlencode({
        "q": f"hotels in {q.location or 'San Francisco'}", "check_in_date": q.check_in.isoformat(),
        "check_out_date": q.check_out.isoformat(), "adults": q.adults, "currency": q.currency,
        "hl": "en", "gl": q.country or "us"})


def _blocks(html: str) -> list[Any]:
    """JSON arrays of every AF_initDataCallback block (balanced-bracket scan)."""
    out: list[list[Any]] = []
    for m in _AF.finditer(html):
        i = m.end()
        while i < len(html) and html[i].isspace():
            i += 1
        if i >= len(html) or html[i] not in "[{":
            continue
        depth, in_str, esc = 0, False, False
        for j in range(i, len(html)):
            c = html[j]
            if in_str:
                esc, in_str = (False, in_str) if esc else (c == "\\", c != '"')
                continue
            if c == '"':
                in_str = True
            elif c in "[{":
                depth += 1
            elif c in "]}":
                depth -= 1
                if depth == 0:
                    try:
                        data = json.loads(html[i:j + 1])
                    except json.JSONDecodeError:
                        break
                    if isinstance(data, list):
                        out.append(data)
                    break
    return out


def _context(value: Any) -> list[Any] | None:
    """The search context list: [3] currency, [4] [[y,m,d],[y,m,d]] dates, [18] destination."""
    if isinstance(value, dict):
        for item in value.values():
            found = _context(item)
            if found is not None:
                return found
    if isinstance(value, list):
        if (len(value) > 18 and isinstance(_get(value, [3]), str)
                and isinstance(_get(value, [4]), list) and isinstance(_get(value, [18]), list)):
            return value
        for item in value:
            found = _context(item)
            if found is not None:
                return found
    return None


def _matches(block: list[Any], q: LodgingQuery) -> bool:
    ctx = _context(block)
    if ctx is None or ctx[3] != q.currency:
        return False
    want = [[q.check_in.year, q.check_in.month, q.check_in.day],
            [q.check_out.year, q.check_out.month, q.check_out.day]]
    return _get(ctx, [4, 0]) == want[0] and _get(ctx, [4, 1]) == want[1]


def served_stay(html: str) -> str | None:
    """Dates and currency the page was actually rendered for (``2026-11-02..2026-11-03 USD``)."""
    for block in _blocks(html):
        ctx = _context(block)
        if ctx is not None:
            d = _get(ctx, [4]) or []
            try:
                return (f"{d[0][0]:04d}-{d[0][1]:02d}-{d[0][2]:02d}.."
                        f"{d[1][0]:04d}-{d[1][1]:02d}-{d[1][2]:02d} {ctx[3]}")
            except (IndexError, TypeError):
                return f"unreadable dates {ctx[3]}"
    return None


def _is_hotel(value: Any) -> bool:
    return (isinstance(value, list) and len(value) > 10 and isinstance(_get(value, [1]), str)
            and (isinstance(_get(value, [2, 0]), list) or isinstance(_get(value, [9]), str)))


def _hotels(value: Any) -> list[list[Any]]:
    if _is_hotel(value):
        return [value]
    if isinstance(value, dict):  # page blocks nest objects such as {"429411180": [...]}
        return [h for item in value.values() for h in _hotels(item)]
    if isinstance(value, list):
        return [h for item in value for h in _hotels(item)]
    return []


def _amount(block: Any) -> Decimal | None:
    """Amount of a price block ``[label, .., value]``: the numeric slot, else the label digits."""
    if not isinstance(block, list) or not isinstance(_get(block, [0]), str):
        return None
    for idx in (4, 2, 1):
        v = _get(block, [idx])
        if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0:
            return Decimal(str(v))
    m = re.search(r"\d[\d,]*(?:\.\d+)?", block[0])
    if m:
        value = Decimal(m.group(0).replace(",", ""))
        return value if value > 0 else None
    return None


def parse_page(html: str, q: LodgingQuery, *, limit: int = MAX_HOTELS) -> list[dict[str, Any]]:
    """Hotel rows of the page blocks that echo the requested stay; prices only as shown."""
    best: list[dict[str, Any]] = []
    for block in _blocks(html):
        if not _matches(block, q):
            continue
        rows, seen = [], set()
        for raw in _hotels(block):
            name = raw[1].strip()
            key = _get(raw, [9]) or name
            if key in seen:
                continue
            seen.add(key)
            nightly_block = _get(raw, [6, 2, 1])
            total_block = next((b for p in ([6, 2, 9], [6, 2, 17], [6, 2, 8])
                                if _amount(b := _get(raw, p)) is not None), None)
            coords = _get(raw, [2, 0])
            address = _get(raw, [2, 1, 0, 0, 0])
            rows.append({
                "name": name, "entity_id": _get(raw, [9]) if isinstance(_get(raw, [9]), str) else None,
                "address": address if isinstance(address, str) else None,
                "lat": _get(coords, [0]) if isinstance(_get(coords, [0]), (int, float)) else None,
                "lng": _get(coords, [1]) if isinstance(_get(coords, [1]), (int, float)) else None,
                "nightly_price": str(_amount(nightly_block)) if _amount(nightly_block) else None,
                "nightly_label": nightly_block[0] if isinstance(nightly_block, list) else None,
                "total_price": str(_amount(total_block)) if total_block is not None else None,
                "total_label": total_block[0] if isinstance(total_block, list) else None,
                "rating": _get(raw, [7, 0, 0]) if isinstance(_get(raw, [7, 0, 0]), (int, float)) else None,
            })
        if len(rows) > len(best):
            best = rows
    return best[:limit]


def _empty_reason(html: str, q: LodgingQuery) -> str:
    served = served_stay(html)
    want = f"{q.check_in}..{q.check_out} {q.currency}"
    if served and served != want:
        # Observed 2026-10-24: the server-rendered page ignores check_in_date/check_out_date
        # and shows Google's default dates; those prices are not for this stay.
        return f"page rendered for {served}, not {want}: prices discarded (one attempt, no RPC)"
    return f"no hotel block echoing the stay in {len(html)} bytes"


def _fetch_primp(url: str, timeout: float) -> str:
    import primp

    client = primp.Client(impersonate="chrome", timeout=timeout, follow_redirects=True)
    res = client.get(url, headers={"accept": "text/html", "accept-language": "en-US,en;q=0.9"})
    if res.status_code != 200:
        raise RuntimeError(f"HTTP {res.status_code}")
    return res.text


class GoogleHotelsDirectSource:
    """One page fetch per search, no retry; failures and empty pages are visible reports."""

    provider = PROVIDER

    def __init__(self, fetch: Fetch | None = None, *, timeout: float = TIMEOUT,
                 clock: Callable[[], datetime] = now_utc) -> None:
        self._fetch = fetch or _fetch_primp
        self.timeout = timeout
        self.clock = clock

    async def search(self, q: LodgingQuery) -> DiscoveryResult:
        started = self.clock()
        url = search_url(q)
        try:
            html = await asyncio.wait_for(asyncio.to_thread(self._fetch, url, self.timeout),
                                          self.timeout + 2)
        except Exception as exc:  # noqa: BLE001 - one attempt; the reason is reported
            kind = "timeout" if isinstance(exc, (asyncio.TimeoutError, TimeoutError)) else "error"
            rep = report(PROVIDER, started, status="failed", termination="error",
                         errors=[f"{kind}: {type(exc).__name__}: {str(exc)[:160]}"])
            return DiscoveryResult(run_report=rep, errors=list(rep.errors))
        from conferge.core.brightdata import block_reason

        if blocked := block_reason(html):
            rep = report(PROVIDER, started, status="degraded", termination="error",
                         errors=[f"blocked:{blocked}"], warnings=[f"{len(html)} bytes, no hotel"])
            return DiscoveryResult(run_report=rep, errors=list(rep.errors))
        rows = parse_page(html, q)
        collected = self.clock()
        items = [SourceRecord(
            provider=PROVIDER, source_id=content_hash(r["entity_id"] or r["name"])[:16],
            source_mode="live", collected_at=collected, payload={"row": r, "search_url": url},
            source_url=url, request_id=None, content_hash=content_hash(r),
        ) for r in rows]
        priced = sum(1 for r in rows if r["total_price"] or r["nightly_price"])
        status = "ok" if items else "degraded"
        rep = report(PROVIDER, started, status=status,
                     termination="exhausted" if items else "error", source_mode="live",
                     fetched=len(items), unique=len(items), pages=1,
                     errors=[] if items else [_empty_reason(html, q)],
                     warnings=[f"{len(items)} hotels, {priced} with a price on the page"])
        return DiscoveryResult(items=items, run_report=rep, errors=list(rep.errors))

    async def fetch_details(self, ref: SourceRef) -> SourceRecord:
        raise RuntimeError("google_hotels_direct has no detail fetch")


def to_lodging(record: SourceRecord, query: LodgingQuery, *, warnings: list[str] | None = None,
               now: datetime | None = None) -> Lodging | None:
    row = record.payload.get("row") or {}
    if not isinstance(row.get("name"), str):
        return None
    total = Decimal(row["total_price"]) if row.get("total_price") else None
    nightly = Decimal(row["nightly_price"]) if row.get("nightly_price") else None
    if total is not None:
        quote = PriceQuote(kind="dated_total", total=total, currency=query.currency)
    elif nightly is not None:
        quote = PriceQuote(kind="from_price", nightly_rate=nightly, currency=query.currency)
    else:
        quote = PriceQuote()
    return build_lodging(
        record, query, name=row["name"], quote=quote, lodging_type="hotel",
        lat=row.get("lat"), lng=row.get("lng"),
        coordinate_precision="exact" if row.get("lat") is not None else "unknown",
        address=row.get("address"), city=query.location, booking_url=None,
        warnings=warnings, now=now,
    )
