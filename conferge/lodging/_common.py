"""Helpers private to the lodging window: money parsing, hashing, run reports.

Money rule: a price that is missing, unparseable or zero is ``None``. Zero is never
accepted as a stay price because several sources (pyairbnb ``price.total.amount``,
Bright Data Airbnb samples) emit ``0`` when the real amount is unknown.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable
from datetime import date, datetime, timezone
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from conferge.core.schemas import RunReport, RunStatus, SourceMode, Termination

BOOKING = "booking"
GOOGLE_HOTELS = "google_hotels"
AIRBNB = "airbnb"

# Bright Data dataset ids, checked on 2026-10-24 against the public catalogue
# https://docs.brightdata.com/scrapers/<id>.json (methods and field names below come from it).
DATASET_BOOKING_SEARCH = "gd_m4bf7a917zfezv9d5"  # collect_by_url (search inputs, no discover)
DATASET_BOOKING_DETAIL = "gd_mdy9ld3p1e0oqlj9g4"  # collect_by_url on a hotel page URL
DATASET_GOOGLE_HOTELS = "gd_mg3gjfmg12tc2n5d4d"  # discover_by_search
DATASET_AIRBNB = "gd_ld7ll037kqy322v05"  # discover_by_location

# Persisted with every record: prices from two markets are not comparable.
MARKET_CONTEXT: dict[str, Any] = {
    "country": "us", "language": "en", "platform": "desktop", "authenticated": False,
}

_MONEY_RE = re.compile(r"-?\d[\d,]*(?:\.\d+)?")
CENT = Decimal("0.01")


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def content_hash(payload: Any) -> str:
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return "sha256:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()


def parse_money(value: Any) -> Decimal | None:
    """Parse ``953``, ``"1,322.50"``, ``"$292"``, ``"US$ 410"``. Zero or negative -> None."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float, Decimal)):
        try:
            amount = Decimal(str(value))
        except InvalidOperation:
            return None
    elif isinstance(value, str):
        match = _MONEY_RE.search(value.replace(" ", " "))
        if not match:
            return None
        try:
            amount = Decimal(match.group(0).replace(",", ""))
        except InvalidOperation:
            return None
    else:
        return None
    if not amount.is_finite() or amount <= 0:
        return None
    return amount


def parse_signed_money(value: Any) -> Decimal | None:
    """Like parse_money but keeps negative amounts (discount lines). Zero -> None."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        amount = Decimal(str(value))
        return amount if amount.is_finite() and amount != 0 else None
    if isinstance(value, str) and value.strip().startswith("-"):
        positive = parse_money(value.strip()[1:])
        return -positive if positive is not None else None
    return parse_money(value)


def quantize(amount: Decimal | None) -> Decimal | None:
    return amount.quantize(CENT, rounding=ROUND_HALF_UP) if amount is not None else None


def parse_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, float):
        return int(value) if value >= 0 else None
    if isinstance(value, str):
        digits = re.sub(r"[^\d]", "", value)
        return int(digits) if digits else None
    return None


def parse_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result == result else None  # NaN -> None


def parse_date(value: Any) -> date | None:
    """Accept ``2026-10-27`` and ``"2026-10-27T00:00:00.000Z"`` (Booking dataset echo)."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not isinstance(value, str) or len(value) < 10:
        return None
    try:
        return date.fromisoformat(value.strip().strip('"')[:10])
    except ValueError:
        return None


def parse_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        low = value.strip().lower()
        if low in {"true", "yes", "1"}:
            return True
        if low in {"false", "no", "0"}:
            return False
    return None


def worst_status(statuses: Iterable[RunStatus]) -> RunStatus:
    ranked = list(statuses)
    if not ranked:
        return "failed"
    if all(s == "failed" for s in ranked):
        return "failed"
    if all(s == "ok" for s in ranked):
        return "ok"
    return "degraded"


def no_peers_status(status: RunStatus, errors: list[str] | None,
                    warnings: list[str] | None) -> tuple[RunStatus, list[str]]:
    """Bright Data out of peers is a degraded source, shown as ``brightdata_no_peers``."""
    from conferge.core.brightdata import NO_PEERS

    out = list(warnings or [])
    if any("no_peers" in t or "cooldown" in t.lower() for t in [*(errors or []), *out]):
        if NO_PEERS not in out:
            out.append(NO_PEERS)
        if status == "failed":
            status = "degraded"
    return status, out


def report(
    provider: str, started_at: datetime, *, status: RunStatus, termination: Termination,
    source_mode: SourceMode = "live", fetched: int = 0, unique: int = 0, pages: int = 0,
    expected: int | None = None, errors: list[str] | None = None,
    warnings: list[str] | None = None, finished_at: datetime | None = None,
) -> RunReport:
    if status == "ok" and termination not in {"exhausted", "not_applicable"}:
        status = "degraded"
    status, warnings = no_peers_status(status, errors, warnings)
    return RunReport(
        provider=provider, started_at=started_at,
        finished_at=max(finished_at or now_utc(), started_at),
        status=status, termination=termination, source_mode=source_mode,
        fetched_count=fetched, unique_count=min(unique, fetched), pages=pages,
        expected_count=expected, errors=errors or [], warnings=warnings or [],
    )


def missing_credentials_report(provider: str, started_at: datetime, detail: str) -> RunReport:
    """No key is not a crash: failed + explicit `missing_credentials` marker for probes."""
    return report(provider, started_at, status="failed", termination="error",
                  errors=[f"missing_credentials: {detail}"])
