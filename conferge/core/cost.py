"""Bright Data usage of this process: requests and records per API.

``requests`` are the calls ``conferge.core.brightdata`` recorded (every call that got an
answer); ``records`` are the rows those calls returned. They differ: one Web Unlocker
request returns one page, from which many rows may be extracted.

No USD figure: no Bright Data response captured so far carried a cost, and a list price
applied to rows is not a bill. ``COST_NOTE`` says so wherever a cost would be expected.
"""

from __future__ import annotations

from typing import Any

from conferge.core import brightdata

COST_NOTE = "cost not read from any Bright Data response"
# brightdata.record_call api name -> name shown in the panel
_API = {"datasets": "datasets", "web_unlocker": "unlocker", "serp": "serp"}


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
            "by_api": by_api, "cost_usd": None, "cost_note": COST_NOTE}


__all__ = ["COST_NOTE", "snapshot"]
