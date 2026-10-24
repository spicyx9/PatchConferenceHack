"""Bright Data usage per product, read from the collected records (never from run reports).

One row per product (Booking, Airbnb, Google Hotels datasets; LinkedIn and Crunchbase
datasets; Web Unlocker pages; SERP), from the cached records the demo serves plus the calls
made by this process (``conferge.core.cost.snapshot``):

* ``records``: rows Bright Data returned for that product.
* ``requests``: API requests behind them, counted from what the records prove: one per
  distinct dataset snapshot, one per record without a snapshot (synchronous scrape), one per
  distinct Web Unlocker page URL, plus recorded runs that returned nothing.
* ``collected_first`` / ``collected_last``: the records' own ``collected_at``.

No USD figure: no captured Bright Data response carried a cost (34 itineraries extracted
from one Unlocker page are one request, and a list price per row would not be a bill).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from conferge.api.provenance import SITE_NAMES
from conferge.core.cost import COST_NOTE
from conferge.core.cost import snapshot as live_snapshot

ROOT = Path(__file__).resolve().parents[2]
CACHE_DIR = ROOT / "data" / "cache"
PROBE_REPORTS = ROOT / "probes"
# SERP lookups recorded by the probe reports (one SERP request per searched name/company).
_SERP_PROBES = {
    "LinkedIn URL search": ("serp_linkedin.md", r"targets: (\d+)\b", r"URLs found: \*\*(\d+)/",
                            r"run at: (\S+)"),
    "Crunchbase URL search": ("crunchbase.md", r"URLs found via SERP: \d+/(\d+)",
                              r"URLs found via SERP: (\d+)/", r"run at: (\S+)"),
}


def _row(product: str, api: str) -> dict[str, Any]:
    return {"product": product, "api": api, "requests": 0, "records": 0, "source": "cached",
            "collected_first": None, "collected_last": None,
            "_snapshots": set(), "_pages": set()}


def _stamp(row: dict[str, Any], at: str | None) -> None:
    if not at:
        return
    row["collected_first"] = min(filter(None, [row["collected_first"], at]))
    row["collected_last"] = max(filter(None, [row["collected_last"], at]))


def _add(row: dict[str, Any], *, at: str | None, snapshot: str | None = None,
         page: str | None = None) -> None:
    row["records"] += 1
    _stamp(row, at)
    if row["api"] == "unlocker":
        row["_pages"].add((page or "?").split("#")[0])
    elif snapshot:
        row["_snapshots"].add(snapshot)
    else:
        row["requests"] += 1  # synchronous scrape: one request per record


def _read(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def cached_products(directory: Path = CACHE_DIR, probes: Path = PROBE_REPORTS) -> list[dict[str, Any]]:
    """Product rows from every record in the cache files (stays, flights, LinkedIn,
    Crunchbase; all collected rows, not only the ones the demo picks to show) and the
    recorded stay runs; SERP lookups from the probe reports in ``probes``."""
    rows: dict[tuple[str, str], dict[str, Any]] = {}

    def row(product: str, api: str) -> dict[str, Any]:
        return rows.setdefault((product, api), _row(product, api))

    for name in ("stays", "flights"):
        for rec in (_read(directory / f"{name}.json") or {}).get("records") or []:
            prov = rec.get("provenance") or {}
            if prov.get("provider") != "brightdata":
                continue
            label = SITE_NAMES.get(prov.get("site") or "", prov.get("site") or "Bright Data")
            _add(row(label, prov["api"]), at=prov.get("collected_at"),
                 snapshot=prov.get("snapshot_id"), page=prov.get("source_url"))
    stays_doc = _read(directory / "stays.json") or {}
    for run in stays_doc.get("runs") or []:  # recorded runs that returned nothing
        if run.get("api") in ("dataset", "unlocker") and not run.get("records"):
            r = row(SITE_NAMES.get(run.get("provider") or "", run.get("provider") or "?"),
                    run["api"])
            r["requests"] += 1
            _stamp(r, run.get("collected_at"))
    for profile in (_read(directory / "linkedin_public.json") or {}).get("profiles") or []:
        _add(row("LinkedIn", "dataset"), at=profile.get("collected_at"),
             snapshot=profile.get("snapshot_id"))
    companies = (_read(directory / "crunchbase_public.json") or {}).get("companies") or []
    for company in companies.values() if isinstance(companies, dict) else companies:
        _add(row("Crunchbase", "dataset"), at=company.get("collected_at"),
             snapshot=company.get("snapshot_id"))
    for product, (name, req_re, rec_re, at_re) in _SERP_PROBES.items():
        try:
            text = (probes / name).read_text(encoding="utf-8")
        except OSError:
            continue
        found = [re.search(rx, text) for rx in (req_re, rec_re, at_re)]
        if not all(found):
            continue
        r = row(product, "serp")
        r["requests"] += int(found[0].group(1))  # type: ignore[union-attr]
        r["records"] += int(found[1].group(1))  # type: ignore[union-attr]
        r["source"] = f"cached (probes/{name})"
        _stamp(r, found[2].group(1))  # type: ignore[union-attr]
    out = []
    for r in rows.values():
        r["requests"] += len(r.pop("_snapshots")) + len(r.pop("_pages"))
        out.append(r)
    return sorted(out, key=lambda r: ({"dataset": 0, "unlocker": 1, "serp": 2}.get(r["api"], 3),
                                      r["product"]))


def live_products() -> list[dict[str, Any]]:
    """Calls made by this process, per API (empty when the demo made none)."""
    snap = live_snapshot()
    names = {"datasets": "dataset", "unlocker": "unlocker", "serp": "serp"}
    return [{"product": "This process", "api": names.get(api, api), "requests": v["requests"],
             "records": v["records"], "source": "live", "collected_first": None,
             "collected_last": None}
            for api, v in snap["by_api"].items() if v["requests"]]


def summary(directory: Path = CACHE_DIR, probes: Path = PROBE_REPORTS) -> dict[str, Any]:
    products = cached_products(directory, probes) + live_products()
    by_api: dict[str, dict[str, int]] = {}
    for p in products:
        slot = by_api.setdefault(p["api"], {"requests": 0, "records": 0})
        slot["requests"] += p["requests"]
        slot["records"] += p["records"]
    return {"products": products, "by_api": by_api,
            "requests": sum(p["requests"] for p in products),
            "records": sum(p["records"] for p in products),
            "cost_usd": None, "cost_note": COST_NOTE}


__all__ = ["cached_products", "live_products", "summary"]
