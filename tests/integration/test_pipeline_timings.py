"""Per-step and per-source durations in /api/v1/pipeline (pipeline.Timings)."""

from __future__ import annotations

import time

from fastapi.testclient import TestClient

from conferge.api.app import create_app
from conferge.api.data import load_fixture
from conferge.api.providers import Providers
from conferge.integration.pipeline import Timings, record_collection
from conferge.integration.sources import SourceSlice


def test_timings_steps_in_order_and_accumulate() -> None:
    t = Timings()
    with t.step("ingest"):
        time.sleep(0.01)
    with t.step("collect"):
        pass
    with t.step("collect"):
        time.sleep(0.01)
    d = t.as_dict([SourceSlice("luma", "01", "fixture", "fixture", "ok", duration_s=0.12)])
    assert [s["step"] for s in d["steps"]] == ["collect", "ingest"]
    assert d["steps"][0]["seconds"] >= 0.01
    assert d["sources"] == [{"source": "luma", "attempted": "fixture", "status": "ok",
                             "records": 0, "seconds": 0.12}]


def test_pipeline_endpoint_serves_timings_and_rank() -> None:
    data = load_fixture()
    t = Timings()
    for step in ("collect", "assemble", "plan", "ingest"):
        with t.step(step):
            pass
    slices = [SourceSlice("luma", "01", "live", "live", "ok", duration_s=0.5),
              SourceSlice("eventbrite", "02", "live", "live", "failed", errors=["boom"], duration_s=0.1)]
    record_collection(data, slices, t)
    client = TestClient(create_app(data=data, found=Providers(), graph_probe=False))
    before = client.get("/api/v1/pipeline").json()
    assert [s["step"] for s in before["timings"]["steps"]] == ["collect", "assemble", "plan", "ingest"]
    assert {s["source"]: s["seconds"] for s in before["timings"]["sources"]} == {"luma": 0.5, "eventbrite": 0.1}
    assert before["sources_report"]["status"] == "failed"  # no slice carries records here
    client.get("/api/v1/people")
    after = client.get("/api/v1/pipeline").json()
    rank = after["timings"]["steps"][-1]
    assert rank["step"] == "rank" and rank["seconds"] >= 0 and "request time" in rank["note"]


def test_e2e_records_timings() -> None:
    from conferge.integration.pipeline import run_e2e_sync

    report = run_e2e_sync("fixture", include_backup=False)
    assert {"collect", "assemble", "plan", "ingest"} <= set(report.timings.steps)
