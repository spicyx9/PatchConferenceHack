"""Web Unlocker hotel search-page parsers, one per site (see unlocker.py).

Observed 2026-10-24 (San Francisco, 2026-10-27 -> 2026-10-30, 2 adults):
- Kayak, Hotels.com, Expedia, Marriott: Bright Data refuses them without KYC (the client
  raises); only a generic JSON-LD parser is wired, unverified on real pages.
- Hilton: Next.js page; hotels in ``__NEXT_DATA__`` dehydratedState query
  ``geocode_hotelSummaryOptions``. Dated rates load client-side and are not in the HTML;
  the embedded ``leadRate`` comes from a query without dates, so it is exposed as
  ``undated_lead_rate`` and never used as a price.
Prices are taken only when literally present for the searched dates; nothing is computed.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urljoin

from selectolax.lexbor import LexborHTMLParser as HTMLParser


def _dec(value: Any) -> str | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return str(Decimal(str(value).replace(",", "").strip()))
    except (InvalidOperation, ValueError):
        return None


def _record(**kw: Any) -> dict[str, Any]:
    base = dict(name=None, address=None, nightly_price=None, total_price=None,
                currency=None, url=None, price_source=None)
    base.update(kw)
    return base


# ---------------------------------------------------------------- JSON-LD (generic)
_HOTEL_TYPES = {"Hotel", "LodgingBusiness", "Resort", "Motel", "Hostel", "BedAndBreakfast"}


def _iter_ld(obj: Any):
    if isinstance(obj, list):
        for x in obj:
            yield from _iter_ld(x)
    elif isinstance(obj, dict):
        yield obj
        for key in ("@graph", "itemListElement", "item"):
            if key in obj:
                yield from _iter_ld(obj[key])


def _ld_address(addr: Any) -> str | None:
    if isinstance(addr, str):
        return addr or None
    if isinstance(addr, dict):
        parts = [addr.get(k) for k in ("streetAddress", "addressLocality",
                                       "addressRegion", "postalCode", "addressCountry")]
        parts = [p if isinstance(p, str) else (p or {}).get("name") for p in parts]
        return ", ".join(p for p in parts if p) or None
    return None


def parse_jsonld_hotels(html: str, base_url: str) -> list[dict[str, Any]]:
    tree = HTMLParser(html)
    out: list[dict[str, Any]] = []
    for node in tree.css('script[type="application/ld+json"]'):
        try:
            data = json.loads(node.text(strip=False) or "")
        except json.JSONDecodeError:
            continue
        for obj in _iter_ld(data):
            types = obj.get("@type")
            types = set(types) if isinstance(types, list) else {types}
            if not types & _HOTEL_TYPES:
                continue
            offers = obj.get("offers") or {}
            if isinstance(offers, list):
                offers = offers[0] if offers else {}
            price = _dec(offers.get("price") or offers.get("lowPrice"))
            url = obj.get("url")
            out.append(_record(
                name=obj.get("name"),
                address=_ld_address(obj.get("address")),
                # JSON-LD does not say per-night vs total; leave it in nightly only if the
                # page labels it so -- here we only record that it is an offers.price.
                nightly_price=None,
                total_price=None,
                offer_price_unlabelled=price,
                currency=offers.get("priceCurrency"),
                url=urljoin(base_url, url) if url else None,
                price_source="json-ld offers.price (period not stated)" if price else None,
            ))
    return out


# ---------------------------------------------------------------- Hilton
def _next_data(html: str) -> dict[str, Any] | None:
    node = HTMLParser(html).css_first("script#__NEXT_DATA__")
    if node is None:
        return None
    try:
        return json.loads(node.text(strip=False) or "")
    except json.JSONDecodeError:
        return None


def parse_hilton(html: str, base_url: str) -> list[dict[str, Any]]:
    data = _next_data(html)
    if not data:
        return []
    queries = (((data.get("props") or {}).get("pageProps") or {})
               .get("dehydratedState") or {}).get("queries") or []
    out: list[dict[str, Any]] = []
    for q in queries:
        key = q.get("queryKey") or [{}]
        op = key[0].get("operationName") if isinstance(key[0], dict) else None
        if op != "geocode_hotelSummaryOptions":
            continue
        variables = key[1] if len(key) > 1 and isinstance(key[1], dict) else {}
        dated = any(k in variables for k in ("arrivalDate", "departureDate"))
        geo = ((q.get("state") or {}).get("data") or {}).get("geocode") or {}
        hotels = (geo.get("hotelSummaryOptions") or {}).get("hotels") or []
        for h in hotels:
            addr = h.get("address") or {}
            address = ", ".join(p for p in (addr.get("addressLine1"), addr.get("city"),
                                            addr.get("state"), addr.get("country")) if p) or None
            url = (h.get("facilityOverview") or {}).get("homeUrlTemplate")
            hh = (h.get("leadRate") or {}).get("hhonors") or {}
            lead = None
            mn, mx = hh.get("min") or {}, hh.get("max") or {}
            if mn.get("rateAmount") is not None or mx.get("rateAmount") is not None:
                lead = {
                    "min": _dec(mn.get("rateAmount")), "min_fmt": mn.get("rateAmountFmt"),
                    "min_rate_plan": (mn.get("ratePlan") or {}).get("ratePlanCode"),
                    "max": _dec(mx.get("rateAmount")), "max_fmt": mx.get("rateAmountFmt"),
                    "max_rate_plan": (mx.get("ratePlan") or {}).get("ratePlanCode"),
                    "dated": dated,
                    "source": "__NEXT_DATA__ dehydratedState geocode_hotelSummaryOptions "
                              "hotels[].leadRate.hhonors (query has no date variables)",
                }
            rec = _record(
                name=h.get("name"),
                address=address,
                url=urljoin(base_url, url) if url else None,
                hotel_code=h.get("ctyhocn"),
                undated_lead_rate=lead,
            )
            if dated and lead and lead["min"]:  # only if Hilton ever dates this query
                rec.update(nightly_price=lead["min"], currency=None,
                           price_source="__NEXT_DATA__ leadRate.hhonors.min.rateAmount")
            out.append(rec)
    return out


PARSERS: dict[str, Callable[[str, str], list[dict[str, Any]]]] = {
    "kayak": parse_jsonld_hotels, "hotels_com": parse_jsonld_hotels,
    "expedia": parse_jsonld_hotels, "marriott": parse_jsonld_hotels, "hilton": parse_hilton,
}
