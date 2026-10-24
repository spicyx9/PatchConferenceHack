"""Which provider and which API produced a stay or a flight, read from its evidence.

Pure function over ``SourceEvidence``: no network, no I/O. The first evidence entry is the
record that produced the item (lodging ``build_lodging`` and the flight normalizers put it
first; later entries are verification/detail fetches).

Contract (consumed by the UI, key names are frozen)::

    {"provider": "brightdata"|"pyairbnb"|"fast-flights"|"fli"|"serpapi"|"fixture"|"unknown",
     "api": "dataset"|"unlocker"|"serp"|"fallback"|"fixture"|"unknown",
     "id": dataset id or unlocker zone or None,
     "site": "booking"|"google_hotels"|"airbnb"|"hilton"|"google_flights"|... or None,
     "snapshot_id": str or None,
     "tier": 0 dataset | 1 unlocker | 2 fallback | 3 fixture/unknown,
     "label": short human text}

Airbnb: both backends share the provider name ``airbnb``. The Bright Data backend sets
``request_id`` (-> ``raw_ref``) to the dataset snapshot id; pyairbnb sets it to None. So an
``airbnb`` evidence with a raw_ref is Bright Data, without one it is pyairbnb.

fast-flights may run through the Bright Data SERP transport, but nothing in its evidence
says so; it is always reported as the fallback.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from conferge.core.schemas import SourceEvidence
from conferge.flights.brightdata_provider import DATASET_ID as DATASET_GOOGLE_FLIGHTS
from conferge.lodging._common import DATASET_AIRBNB, DATASET_BOOKING_SEARCH, DATASET_GOOGLE_HOTELS

DATASETS = {
    "booking": DATASET_BOOKING_SEARCH,
    "google_hotels": DATASET_GOOGLE_HOTELS,
    "airbnb": DATASET_AIRBNB,
    "google_flights": DATASET_GOOGLE_FLIGHTS,
}
SITE_NAMES = {
    "booking": "Booking", "google_hotels": "Google Hotels", "airbnb": "Airbnb",
    "google_flights": "Google Flights", "hilton": "Hilton", "marriott": "Marriott",
    "kayak": "Kayak", "expedia": "Expedia", "hotels_com": "Hotels.com",
}
TIERS = {"dataset": 0, "unlocker": 1, "serp": 2, "fallback": 2, "fixture": 3, "unknown": 3}


def _site_name(site: str | None) -> str:
    return SITE_NAMES.get(site or "", (site or "").replace("_", " ").title())


def _out(provider: str, api: str, label: str, *, id: str | None = None,  # noqa: A002
         site: str | None = None, snapshot_id: str | None = None) -> dict[str, Any]:
    return {"provider": provider, "api": api, "id": id, "site": site,
            "snapshot_id": snapshot_id, "tier": TIERS[api], "label": label}


def _dataset(site: str, snapshot: str | None) -> dict[str, Any]:
    ds = DATASETS[site]
    return _out("brightdata", "dataset", f"Bright Data dataset {ds} ({_site_name(site)})",
                id=ds, site=site, snapshot_id=snapshot)


def _unlocker(raw_ref: str | None, default_site: str | None = None) -> dict[str, Any]:
    parts = (raw_ref or "").split(":")
    zone = parts[1] if len(parts) > 1 and parts[1] else None
    site = parts[2] if len(parts) > 2 and parts[2] else default_site
    label = "Bright Data Web Unlocker" + (f" {zone}" if zone else "")
    if site:
        label += f" ({_site_name(site)})"
    return _out("brightdata", "unlocker", label, id=zone, site=site)


def source_of(evidence: Sequence[SourceEvidence] | None) -> dict[str, Any]:
    """Provider/API provenance of an item, from its evidence list (first entry wins)."""
    if not evidence:
        return _out("unknown", "unknown", "Unknown source")
    ev = evidence[0]
    provider = (ev.provider or "").lower()
    raw = ev.raw_ref
    if ev.source_mode == "fixture" or provider.startswith("fixture"):
        return _out("fixture", "fixture", "Fixture")
    if provider in ("booking", "google_hotels"):
        return _dataset(provider, raw)
    if provider == "airbnb":
        if raw:
            return _dataset("airbnb", raw)
        return _out("pyairbnb", "fallback", "Fallback pyairbnb", site="airbnb")
    if provider in ("unlocker", "brightdata_unlocker_google_flights"):
        default = "google_flights" if provider != "unlocker" else None
        return _unlocker(raw, default)
    if provider == "brightdata_google_flights":
        return _dataset("google_flights", raw)
    if provider == "fast_flights_google_flights":
        return _out("fast-flights", "fallback", "Fallback fast-flights", site="google_flights")
    if provider == "google_flights_fli":
        return _out("fli", "fallback", "Fallback fli (Google Flights)", site="google_flights")
    if provider.startswith("serpapi"):
        return _out("serpapi", "serp", "SerpApi Google Flights", site="google_flights")
    return _out("unknown", "unknown", "Unknown source")


__all__ = ["source_of"]
