"""Bright Data dataset collection shared by the lodging adapters (via core.brightdata only).

``/datasets/v3/scrape`` answers synchronously (< 1 min) or with HTTP 202 + snapshot_id;
the snapshot is then polled for at most ``max_wait`` seconds. Rows carrying an ``error``
or ``error_code`` are excluded and counted, never repaired.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any

from conferge.core.brightdata import NO_PEERS, BrightDataClient, BrightDataError


class SnapshotPending(BrightDataError):
    """Snapshot still running after the polling budget; carries the id for a later fetch."""

    def __init__(self, snapshot_id: str) -> None:
        super().__init__(f"Bright Data snapshot {snapshot_id} still running")
        self.snapshot_id = snapshot_id


@dataclass
class Collected:
    rows: list[dict[str, Any]] = field(default_factory=list)
    error_rows: int = 0
    snapshot_id: str | None = None
    warnings: list[str] = field(default_factory=list)


def has_key(client: BrightDataClient | None) -> bool:
    return client is not None and bool(getattr(client, "_api_key", None))


def _rows(data: Any) -> list[Any]:
    if data is None:
        return []
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("data", "results", "items"):
            if isinstance(data.get(key), list):
                return data[key]
        return [data]
    raise BrightDataError("Bright Data payload is neither a list nor an object")


async def collect(
    client: BrightDataClient, dataset_id: str, inputs: list[dict[str, Any]], *,
    method: str | None = None, limit_per_input: int | None = 10,
    poll_interval: float = 5.0, max_wait: float = 240.0,
) -> Collected:
    out = await client.scrape_dataset(dataset_id, inputs, method=method,
                                      limit_per_input=limit_per_input)
    snapshot_id = out.snapshot_id
    deadline = time.monotonic() + max_wait
    while out.status == "running":
        if not snapshot_id:
            raise BrightDataError("Bright Data running without snapshot_id")
        if time.monotonic() >= deadline:
            raise SnapshotPending(snapshot_id)
        await asyncio.sleep(poll_interval)
        out = await client.snapshot_results(snapshot_id)
    result = Collected(snapshot_id=snapshot_id)
    for row in _rows(out.data):
        if not isinstance(row, dict):
            result.error_rows += 1
            continue
        if row.get("error") or row.get("error_code"):
            result.error_rows += 1
            continue
        result.rows.append(row)
    if result.error_rows:
        result.warnings.append(f"{dataset_id}: {result.error_rows} row(s) with error excluded")
    if NO_PEERS in out.warnings:
        result.warnings.append(NO_PEERS)
    return result
