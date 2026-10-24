"""Data pipeline panel: one row per collection run, built only from real RunReports.

Rows say how each source was collected (``brightdata`` / ``direct`` / ``fallback``),
which Bright Data API (``dataset`` / ``unlocker`` / ``serp``) when relevant, the record
count, collected_at, the RunReport outcome and an estimated cost for Bright Data rows.
Nothing here is a constant: a source that did not run has no row.
"""

from __future__ import annotations

import json
import re
from decimal import Decimal
from pathlib import Path
from typing import Any

from conferge.core.brightdata import NO_PEERS
from conferge.core.schemas import RunReport

HEADLINE = ("Agents never fetch the web at query time: all reasoning runs on the stored, "
            "deduplicated, provenance-tagged graph.")
# Estimate only: Bright Data pay-as-you-go list price, USD 1.50 per 1,000 records.
USD_PER_1000_RECORDS = Decimal("1.5")
_DATASET_PROVIDERS = {"booking", "google_hotels", "brightdata_google_flights", "brightdata",
                      "facebook_events", "brightdata:linkedin"}
_UNLOCKER_USE = re.compile(r"via Web Unlocker (\d+)x")


def _api(report: RunReport) -> str | None:
    if report.provider in _DATASET_PROVIDERS:
        return "dataset"
    if report.provider == "brightdata_serp":
        return "serp"
    used = [int(m.group(1)) for w in report.warnings if (m := _UNLOCKER_USE.search(w))]
    return "unlocker" if any(used) else None


def row(source: str, report: RunReport, *, fallback: bool = False) -> dict[str, Any]:
    api = None if fallback else _api(report)
    kind = "fallback" if fallback or report.source_mode == "fixture" else (
        "brightdata" if api else "direct")
    records = report.unique_count
    estimate = None
    if kind == "brightdata" and report.status != "failed":
        estimate = str((Decimal(records) * USD_PER_1000_RECORDS / 1000).quantize(Decimal("0.0001")))
    return {
        "source": source, "provider": report.provider, "kind": kind, "brightdata_api": api,
        "records": records, "collected_at": report.finished_at.isoformat(),
        "cached": report.source_mode == "cached",
        "status": report.status, "termination": report.termination,
        # brightdata_no_peers is shown as is (Bright Data out of peers after 15/30/60 s retries).
        "reason": NO_PEERS if NO_PEERS in report.warnings else (
            report.errors[0] if report.errors else None),
        "estimated_cost_usd": estimate,
        "estimate_basis": "records x 1.5 / 1000 (estimate)" if estimate is not None else None,
    }


def build_rows(slices: list[Any], travel: dict[str, Any], travel_fallback: dict[str, bool]) -> list[dict[str, Any]]:
    """``slices``: SourceSlice list; ``travel``: LiveDomain per domain; ``travel_fallback``:
    True when assembly kept the API fixture for that domain."""
    rows = []
    for s in slices:
        for report in s.reports:
            rows.append(row(s.name, report, fallback=s.attempted == "fixture"))
    for name, domain in travel.items():
        if domain is None:
            continue
        for report in getattr(domain, "reports", []):
            rows.append(row(name, report))
        for note in getattr(domain, "warnings", []):
            if "skipped" in note and "Bright Data" in note:
                rows.append({"source": name, "provider": "brightdata", "kind": "skipped",
                             "brightdata_api": "dataset", "records": None, "collected_at": None,
                             "status": "skipped", "termination": None, "reason": note,
                             "estimated_cost_usd": None, "estimate_basis": None})
        if travel_fallback.get(name):
            rows.append({"source": name, "provider": "api fixture", "kind": "fallback",
                         "brightdata_api": None, "records": None, "collected_at": None,
                         "status": "fixture", "termination": None,
                         "reason": "live results unusable; labelled fixture shown",
                         "estimated_cost_usd": None, "estimate_basis": None})
    rows.extend(fli_rows())  # Google Flights secondary source, as of the last fli probe
    return rows


BLOCK_MATRIX = Path(__file__).resolve().parents[2] / "data" / "block_matrix.json"
_ATTEMPTS = ("plain_default_ua", "plain_browser_ua", "brightdata_unlocker", "brightdata_dataset")


FLI_RUN = Path(__file__).resolve().parents[2] / "data" / "cache" / "fli_run.json"


def fli_rows(path: Path = FLI_RUN) -> list[dict[str, Any]]:
    """Google Flights sources as of the last fli probe run (scripts/probes/flights_fli.py)."""
    try:
        run = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    gf = run.get("google_flights") or {}
    reason = None if run["status"] == "ok" else "; ".join(run.get("errors") or []) or None
    summary = (f"Google Flights: Bright Data dataset {gf.get('dataset')}, Web Unlocker "
               f"{gf.get('unlocker')}, fli {gf.get('fli')}")
    return [{"source": "flights", "provider": run["provider"], "kind": "direct",
             "brightdata_api": None, "records": run.get("records", 0),
             "collected_at": run.get("run_at"), "status": run["status"],
             "termination": "exhausted" if run["status"] == "ok" else "error",
             "reason": f"{summary}" + (f" ({reason})" if reason else ""),
             "estimated_cost_usd": None, "estimate_basis": None}]


def reachability(path: Path | None = None) -> dict[str, Any] | None:
    """Last block-matrix run (``scripts/probes/block_matrix.py``), or None if never run."""
    try:
        report = json.loads((path or BLOCK_MATRIX).read_text())
    except (OSError, ValueError):
        return None
    return {
        "run_at": report["run_at"], "datasets_read_at": report.get("datasets_read_at"),
        "zone": report["zone"], "counts": report["counts"],
        "sites": [{"site": s["site"],
                   **{k: s["attempts"].get(k, {}).get("class", "not_run") for k in _ATTEMPTS},
                   "detail": s["attempts"]["brightdata_unlocker"]["detail"],
                   "dataset_detail": s["attempts"].get("brightdata_dataset", {}).get("detail")}
                  for s in report["sites"]],
    }


def totals(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_api: dict[str, int] = {}
    cost = Decimal(0)
    for r in rows:
        if r["kind"] == "brightdata" and r["status"] != "failed":
            by_api[r["brightdata_api"]] = by_api.get(r["brightdata_api"], 0) + (r["records"] or 0)
            cost += Decimal(r["estimated_cost_usd"] or 0)
    return {"brightdata_records_by_api": by_api, "brightdata_records": sum(by_api.values()),
            "estimated_cost_usd": str(cost), "estimate": True}
