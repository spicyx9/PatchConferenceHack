"""Live Bright Data cost counter for this process (after brightdata/open-enrich cost-tracker.ts).

Counts the calls ``conferge.core.brightdata`` recorded (every call that got an answer) and
multiplies by one flat price. Estimate only: the real per-call price was not verified
against the account's plan, so the figure is always served with ``estimate: true``.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from conferge.core import brightdata

# Estimate, real price not verified: flat USD per Bright Data call, all APIs alike.
BRIGHT_DATA_USD_PER_CALL = Decimal("0.0015")
# brightdata.record_call api name -> name shown in the panel
_API = {"datasets": "datasets", "web_unlocker": "unlocker", "serp": "serp"}


def snapshot(calls: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """{calls, by_api, usd, estimate: true} from ``brightdata.calls()`` (or ``calls``)."""
    calls = brightdata.calls() if calls is None else calls
    by_api = dict.fromkeys(_API.values(), 0)
    for c in calls:
        api = _API.get(str(c.get("api")), str(c.get("api")))
        by_api[api] = by_api.get(api, 0) + 1
    usd = (Decimal(len(calls)) * BRIGHT_DATA_USD_PER_CALL).quantize(Decimal("0.0001"))
    return {"calls": len(calls), "by_api": by_api, "usd": str(usd), "estimate": True,
            "usd_per_call": str(BRIGHT_DATA_USD_PER_CALL),
            "basis": "calls x USD 0.0015 (estimate, real price not verified)"}


__all__ = ["BRIGHT_DATA_USD_PER_CALL", "snapshot"]
