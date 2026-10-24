"""Bright Data usage of this process: requests and records per API, list-price estimate.

``requests`` are the calls ``conferge.core.brightdata`` recorded (every call that got an
answer); ``records`` are the rows those calls returned. They differ: one Web Unlocker
request returns one page, from which many rows may be extracted.

The cost is a list-price estimate, never a bill: Bright Data datasets list at USD 1.50 per
1,000 records, so only dataset records are priced. Web Unlocker and SERP are billed per
request on plans we have not verified, so no figure is computed for them.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from conferge.core import brightdata

# List price estimate, not billed: Bright Data datasets, USD per 1,000 records.
DATASET_USD_PER_1000_RECORDS = Decimal("1.5")
COST_LABEL = "list price estimate, not billed"
# brightdata.record_call api name -> name shown in the panel
_API = {"datasets": "datasets", "web_unlocker": "unlocker", "serp": "serp"}


def dataset_cost(records: int) -> str:
    """List-price estimate for ``records`` dataset rows, as a decimal string."""
    return str((Decimal(records) * DATASET_USD_PER_1000_RECORDS / 1000).quantize(Decimal("0.0001")))


def snapshot(calls: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Requests and records per API from ``brightdata.calls()`` (or ``calls``)."""
    calls = brightdata.calls() if calls is None else calls
    by_api = {api: {"requests": 0, "records": 0} for api in _API.values()}
    for c in calls:
        api = _API.get(str(c.get("api")), str(c.get("api")))
        slot = by_api.setdefault(api, {"requests": 0, "records": 0})
        slot["requests"] += 1
        slot["records"] += int(c.get("rows") or 0)
    return {"requests": sum(v["requests"] for v in by_api.values()),
            "records": sum(v["records"] for v in by_api.values()),
            "by_api": by_api, "usd": dataset_cost(by_api["datasets"]["records"]),
            "estimate": True, "cost_label": COST_LABEL,
            "basis": "dataset records x USD 1.50 / 1,000 (list price); Unlocker and SERP not priced"}


__all__ = ["COST_LABEL", "DATASET_USD_PER_1000_RECORDS", "dataset_cost", "snapshot"]
