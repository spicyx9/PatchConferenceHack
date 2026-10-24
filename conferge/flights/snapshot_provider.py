"""Google Flights dataset snapshots collected out of the demo path (scripts/probes/flights_collect.py).

The Bright Data dataset gd_mhng7wen1rw0a3gvpf takes minutes, so the demo never waits for it:
the collector writes data/snapshots/google_flights_<date>.json and this provider serves the
newest file younger than 24 h. Offers are relabelled ``cached`` (source_mode and price_status)
with the snapshot's own collected_at and snapshot id; an older or missing file is a failed
report, so the router falls through to the next provider.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from conferge.core.schemas import FlightOffer, RunReport, SourceRecord
from conferge.flights.brightdata_provider import (
    DATASET_ID,
    PROVIDER,
    _record_id,
    record_to_raw_offer,
)
from conferge.flights.normalize import NormalizationError, build_offer

SNAPSHOT_DIR = Path(__file__).resolve().parents[2] / "data" / "snapshots"
MAX_AGE = timedelta(hours=24)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def latest_snapshot(directory: Path = SNAPSHOT_DIR, *, now: datetime | None = None,
                    ) -> tuple[dict[str, Any] | None, str]:
    """(snapshot, reason): the newest ready snapshot younger than MAX_AGE, else None and why."""
    now = now or _now()
    files = sorted(directory.glob("google_flights_*.json"), reverse=True)
    if not files:
        return None, f"no snapshot in {directory.name}/"
    for path in files:
        try:
            snap = json.loads(path.read_text(encoding="utf-8"))
            collected = datetime.fromisoformat(snap["collected_at"])
        except (OSError, ValueError, KeyError) as exc:
            return None, f"{path.name}: unreadable ({type(exc).__name__})"
        if snap.get("status") != "ready" or not snap.get("rows"):
            continue
        age = now - collected
        if age > MAX_AGE:
            return None, f"{path.name}: {age.total_seconds() / 3600:.1f} h old (> 24 h)"
        return {**snap, "_path": path.name, "_collected": collected}, "ok"
    return None, "no ready snapshot with rows"


class GoogleFlightsSnapshotProvider:
    def __init__(self, directory: Path = SNAPSHOT_DIR, *,
                 clock: Callable[[], datetime] = _now) -> None:
        self.directory = directory
        self.clock = clock

    def _report(self, started: datetime, status: str, *, fetched: int = 0,
                errors: list[str] | None = None, warnings: list[str] | None = None) -> RunReport:
        return RunReport(provider=f"{PROVIDER}_snapshot", started_at=started,
                         finished_at=max(self.clock(), started), status=status,
                         termination="exhausted" if status == "ok" else "error",
                         source_mode="cached", fetched_count=fetched, unique_count=fetched,
                         errors=errors or [], warnings=warnings or [])

    async def search_round_trip(self, origin: str, destination: str, departure: date,
                                return_date: date, *, adults: int = 1, cabin: str = "economy",
                                ) -> tuple[list[FlightOffer], RunReport]:
        started = self.clock()
        snap, why = latest_snapshot(self.directory, now=started)
        if snap is None:
            return [], self._report(started, "failed", errors=[f"dataset snapshot: {why}"])
        snapshot_id = next((s["snapshot_id"] for s in reversed(snap.get("snapshots", []))
                            if s.get("snapshot_id")), None)
        offers, warnings = [], []
        for row in snap["rows"]:
            if not isinstance(row, dict) or row.get("error") or row.get("error_code"):
                continue
            record = SourceRecord(provider=PROVIDER, source_id=_record_id(row),
                                  source_mode="cached", collected_at=snap["_collected"],
                                  payload=row, request_id=snapshot_id)
            try:
                offer = build_offer(record_to_raw_offer(record), snap["_collected"],
                                    price_status="cached")
            except (KeyError, NormalizationError, ValueError) as exc:
                warnings.append(f"row skipped: {str(exc)[:120]}")
                continue
            first, last = offer.slices[0].segments[0], offer.slices[0].segments[-1]
            if first.origin_iata == origin and last.destination_iata == destination:
                offers.append(offer)
        status = "ok" if offers else "failed"
        return offers, self._report(
            started, status, fetched=len(offers),
            errors=[] if offers else [f"snapshot {snap['_path']}: no offer {origin}-{destination}"],
            warnings=[f"dataset {DATASET_ID} snapshot {snapshot_id} from {snap['_path']}, "
                      f"collected {snap['collected_at']}", *warnings[:5]])
