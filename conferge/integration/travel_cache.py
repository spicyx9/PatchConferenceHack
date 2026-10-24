"""Travel cache: normalized stays and flights from earlier Bright Data collections.

``data/cache/stays.json`` and ``data/cache/flights.json`` hold normalized records (never
raw HTML, never LinkedIn) with their provenance: provider, api, dataset_id or zone,
snapshot_id, source_url, collected_at, price_status. ``scripts/probes/build_travel_cache.py``
writes them from probe outputs without any new call. ``make demo`` serves them by default
when present (``--travel cached``): records keep their original collected_at and are
relabelled ``cached``, never ``live``. Without a cache the labelled fixtures stay.
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from conferge.api.provenance import source_of
from conferge.core.brightdata import NO_PEERS
from conferge.core.schemas import FlightOffer, Lodging, RunReport
from conferge.flights.round_trip_total import as_stored
from conferge.integration.stays_flights import LiveDomain, dedupe_flights, pick_flights, pick_stays

CACHE_DIR = Path(__file__).resolve().parents[2] / "data" / "cache"
FILES = {"stays": "stays.json", "flights": "flights.json"}
_MODELS: dict[str, type] = {"stays": Lodging, "flights": FlightOffer}
# Report provider names the data pipeline panel already maps to a Bright Data API.
_REPORT_PROVIDER = {("dataset", "booking"): "booking", ("dataset", "google_hotels"): "google_hotels",
                    ("dataset", "airbnb"): "brightdata",
                    ("dataset", "google_flights"): "brightdata_google_flights"}


def provenance(item: Any) -> dict[str, Any]:
    src = source_of(item.evidence)
    ev = item.evidence[0] if item.evidence else None
    return {"provider": src["provider"], "api": src["api"], "id": src["id"],
            "site": src["site"], "snapshot_id": src["snapshot_id"], "label": src["label"],
            "source_url": str(ev.source_url) if ev and ev.source_url else None,
            "collected_at": ev.collected_at.isoformat() if ev and ev.collected_at else None,
            "price_status": item.price_status}


def build(domain: str, items: list[Any], *, sources: list[str], generated_at: datetime,
          ) -> dict[str, Any]:
    """Cache document for ``items`` (Lodging or FlightOffer), with per-record provenance."""
    stamps = [datetime.fromisoformat(p["collected_at"]) for p in map(provenance, items)
              if p["collected_at"]]
    return {
        "kind": "conferge.travel_cache", "domain": domain, "generated_at": generated_at.isoformat(),
        "collected_at": max(stamps).isoformat() if stamps else None,
        "sources": sources,
        "records": [{"provenance": provenance(i), "record": json.loads(i.model_dump_json())}
                    for i in items],
    }


def _cached(item: Any) -> Any:
    evidence = [e.model_copy(update={"source_mode": "cached"}) if e.source_mode == "live" else e
                for e in item.evidence]
    return item.model_copy(update={"evidence": evidence})


def _reports(domain: str, records: list[dict[str, Any]], items: list[Any]) -> list[RunReport]:
    """One RunReport per (api, site) group, finished at that group's latest collected_at."""
    groups: dict[tuple[str, str | None], list[datetime]] = {}
    for rec in records:
        p = rec["provenance"]
        if p["provider"] != "brightdata":
            continue
        at = datetime.fromisoformat(p["collected_at"]) if p["collected_at"] else None
        groups.setdefault((p["api"], p["site"]), []).append(at)  # type: ignore[arg-type]
    out = []
    for (api, site), stamps in groups.items():
        known = [s for s in stamps if s is not None]
        if not known:
            continue
        provider = _REPORT_PROVIDER.get((api, site or ""), f"brightdata_{api}_{site}")
        warnings = [f"served from data/cache/{FILES[domain]}, collected {max(known).isoformat()}"]
        if api == "unlocker":
            warnings.append("via Web Unlocker 1x")  # one search page per site and date pair
        out.append(RunReport(provider=provider, started_at=min(known), finished_at=max(known),
                             status="ok", termination="exhausted", source_mode="cached",
                             fetched_count=len(stamps), unique_count=len(stamps),
                             warnings=warnings))
    return out


def _run_reports(doc: dict[str, Any]) -> list[RunReport]:
    """Recorded collection runs without records (e.g. Google Hotels: no_peers, wrong dates)."""
    out = []
    for run in doc.get("runs") or []:
        at = datetime.fromisoformat(run["collected_at"])
        out.append(RunReport(provider=run["provider"], started_at=at, finished_at=at,
                             status=run["status"], termination="error", source_mode="cached",
                             fetched_count=run.get("records", 0), unique_count=run.get("records", 0),
                             errors=[run["reason"]] if run.get("reason") else [],
                             warnings=[f"recorded run, {run.get('records', 0)} records",
                                       *([NO_PEERS] if "no_peers" in (run.get("reason") or "")
                                         else [])]))
    return out


def add_run(domain: str, run: dict[str, Any], directory: Path = CACHE_DIR) -> None:
    """Record a run (provider, status, records, reason, collected_at) in a cache file."""
    path = directory / FILES[domain]
    doc = json.loads(path.read_text(encoding="utf-8"))
    runs = [r for r in doc.get("runs") or [] if r["provider"] != run["provider"]]
    doc["runs"] = [*runs, run]
    path.write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")


def load(directory: Path = CACHE_DIR, *, flight_alternatives: bool = False) -> dict[str, LiveDomain] | None:
    """LiveDomain per domain from the cache files, or None when no cache file exists."""
    found: dict[str, LiveDomain] = {}
    for domain, name in FILES.items():
        path = directory / name
        if not path.exists():
            continue
        doc = json.loads(path.read_text(encoding="utf-8"))
        items = [_cached(_MODELS[domain].model_validate(r["record"])) for r in doc["records"]]
        if domain == "flights":  # a record saved before quoted_total existed, read as stored now
            items = [as_stored(i) for i in items]
        picked = (pick_stays(items) if domain == "stays" else
                  dedupe_flights(items) if flight_alternatives else pick_flights(items))
        labels = Counter(r["provenance"]["label"] for r in doc["records"])
        collected = datetime.fromisoformat(doc["collected_at"]) if doc.get("collected_at") else None
        found[domain] = LiveDomain(
            domain, picked, "cached", "ok" if picked else "failed", collected,
            [f"cache {path.name}: {len(items)} records collected {doc.get('collected_at')}, "
             f"{len(picked)} shown",
             "cache sources: " + ", ".join(f"{k} x{v}" for k, v in labels.most_common())],
            [] if picked else [f"cache {path.name}: no usable record"],
            [*_reports(domain, doc["records"], items), *_run_reports(doc)],
        )
    return found or None


def available(directory: Path = CACHE_DIR) -> bool:
    return any((directory / name).exists() for name in FILES.values())


__all__ = ["CACHE_DIR", "add_run", "available", "build", "load", "provenance"]
