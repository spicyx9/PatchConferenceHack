from __future__ import annotations

from datetime import datetime, timezone

from conferge.core.schemas import RunReport
from conferge.integration.pipeline_view import HEADLINE, build_rows, totals
from conferge.integration.sources import SourceSlice
from conferge.integration.stays_flights import LiveDomain

AT = datetime(2026, 10, 24, 18, 0, tzinfo=timezone.utc)


def _report(provider: str, n: int, status: str = "ok", mode: str = "live", **kw) -> RunReport:  # type: ignore[no-untyped-def]
    return RunReport(provider=provider, started_at=AT, finished_at=AT, status=status,
                     termination="exhausted" if status == "ok" else "error", source_mode=mode,
                     fetched_count=n, unique_count=n, **kw)


def test_rows_come_from_reports_with_kind_and_api() -> None:
    slices = [
        SourceSlice("official", "03", "live", "live", "ok", reports=[_report(
            "rainfocus:github-universe-2026", 466,
            warnings=["transport: githubuniverse.com via Web Unlocker 2x, direct 9x"])]),
        SourceSlice("luma", "01", "fixture", "fixture", "ok", reports=[_report("luma", 12, mode="fixture")]),
        SourceSlice("discovery", "04", "live", "live", "failed", reports=[_report(
            "brightdata_serp", 0, status="failed", errors=["BRIGHTDATA_SERP_ZONE not configured"])]),
    ]
    travel = {"stays": LiveDomain("stays", reports=[_report("google_hotels", 40), _report("airbnb", 5)]),
              "flights": LiveDomain("flights", reports=[_report("brightdata_google_flights", 0, status="failed",
                                                                 errors=["Bright Data /datasets/v3/scrape: HTTP 401"])])}
    rows = build_rows(slices, travel, {"stays": False, "flights": True})
    by = {(r["source"], r["provider"]): r for r in rows}
    assert by[("official", "rainfocus:github-universe-2026")]["brightdata_api"] == "unlocker"
    assert by[("luma", "luma")]["kind"] == "fallback"
    serp = by[("discovery", "brightdata_serp")]
    assert serp["status"] == "failed" and serp["reason"] == "BRIGHTDATA_SERP_ZONE not configured"
    assert "estimated_cost_usd" not in serp  # no invented USD figure on any row
    hotels = by[("stays", "google_hotels")]
    assert (hotels["kind"], hotels["brightdata_api"], hotels["records"]) == ("brightdata", "dataset", 40)
    assert by[("stays", "airbnb")]["kind"] == "direct"
    assert by[("flights", "api fixture")]["kind"] == "fallback"
    t = totals(rows)
    assert t["brightdata_records_by_api"] == {"unlocker": 466, "dataset": 40}
    assert t["cost_usd"] is None and "not read from any Bright Data response" in t["cost_note"]
    assert "fetch the web" in HEADLINE


def test_pipeline_endpoint_serves_rows_and_headline() -> None:
    from fastapi.testclient import TestClient

    from conferge.api.app import create_app
    from conferge.api.data import load_fixture
    from conferge.api.providers import Providers

    data = load_fixture()
    data.pipeline = build_rows([], {"stays": LiveDomain("stays", reports=[_report("booking", 3)])}, {})
    body = TestClient(create_app(data=data, found=Providers(), graph_probe=False)).get("/api/v1/pipeline").json()
    assert body["headline"].startswith("Agents never fetch the web at query time")
    assert body["rows"][0]["provider"] == "booking" and body["totals"]["brightdata_records"] == 3


def test_no_usd_on_any_row_and_collected_at_override() -> None:
    from conferge.integration.pipeline_view import row

    unlocker = _report("brightdata_unlocker_google_flights", 34, warnings=["via Web Unlocker 1x"])
    r = row("flights", unlocker)
    assert r["brightdata_api"] == "unlocker" and not {k for k in r if "usd" in k or "estimate" in k}
    ds = row("linkedin", _report("brightdata:linkedin", 9), collected_at="2026-10-24T20:07:29Z")
    assert not {k for k in ds if "usd" in k or "estimate" in k}  # no list price on dataset rows either
    assert ds["collected_at"] == "2026-10-24T20:07:29Z"
