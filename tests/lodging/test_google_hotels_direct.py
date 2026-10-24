from __future__ import annotations

import asyncio
import json
from datetime import date

from conferge.api.provenance import source_of
from conferge.lodging.google_hotels_direct import GoogleHotelsDirectSource, parse_page
from conferge.lodging.models import LodgingQuery
from conferge.lodging.normalize import normalize

Q = LodgingQuery(check_in=date(2026, 10, 27), check_out=date(2026, 10, 30), adults=2,
                 currency="USD", limit=15, verify_top=0)


def _hotel(name: str, *, nightly: int | None = None, total: int | None = None) -> list:
    prices = [None] * 10
    if nightly:
        prices[1] = [f"${nightly}", None, nightly]
    if total:
        prices[9] = [f"${total:,} total", None, total]
    return [None, name, [[37.80, -122.43], [[[f"{name} street 1"]]]], None, None, None,
            [None, None, prices], [[4.3, 1200]], None, f"ent-{name}", None, None]


def _page(dates: list[list[int]], hotels: list[list]) -> str:
    ctx = [None, None, None, "USD", [*dates, 2, None, 0], *([None] * 13),
           ["/m/0d6lp", "San Francisco", "ent-sf"]]
    data = [{"429411180": [ctx, hotels]}]
    return ("<html><head><title>hotels in San Francisco - Google Hotel Search</title></head>"
            f"<script>AF_initDataCallback({{key: 'ds:0', hash: '2', data:{json.dumps(data)}, "
            "sideChannel: {}});</script></html>")


STAY = [[2026, 10, 27], [2026, 10, 30]]


def test_total_is_quoted_total_nightly_is_indicative_none_stays_null() -> None:
    page = _page(STAY, [_hotel("Total Inn", nightly=214, total=642),
                        _hotel("Night Hotel", nightly=199), _hotel("No Price Lodge")])
    result = asyncio.run(GoogleHotelsDirectSource(fetch=lambda u, t: page).search(Q))
    assert result.run_report.status == "ok" and len(result.items) == 3
    stays = {s.name: s for s in (normalize(r, Q, warnings=[]) for r in result.items)}
    assert stays["Total Inn"].price_status == "quoted_total"
    assert str(stays["Total Inn"].total_price) == "642.00"
    assert stays["Night Hotel"].price_status == "indicative"
    assert stays["Night Hotel"].total_price is None and str(stays["Night Hotel"].nightly_avg) == "199.00"
    assert stays["No Price Lodge"].total_price is None and stays["No Price Lodge"].nightly_avg is None
    src = source_of(stays["Total Inn"].evidence)
    assert src["provider"] == "google_hotels_direct" and src["tier"] == 2  # after datasets (0)
    assert all(str(s.evidence[0].source_url).startswith("https://www.google.com/travel/search?")
               for s in stays.values())


def test_page_rendered_for_other_dates_is_discarded_with_its_reason() -> None:
    page = _page([[2026, 11, 2], [2026, 11, 3]], [_hotel("Wrong Dates Inn", total=300)])
    assert parse_page(page, Q) == []
    result = asyncio.run(GoogleHotelsDirectSource(fetch=lambda u, t: page).search(Q))
    assert result.items == [] and result.run_report.status == "degraded"
    assert result.run_report.errors == [
        "page rendered for 2026-11-02..2026-11-03 USD, not 2026-10-27..2026-10-30 USD: "
        "prices discarded (one attempt, no RPC)"]


def test_blocked_page_and_fetch_error_are_visible_one_attempt() -> None:
    calls: list[str] = []

    def blocked(url: str, timeout: float) -> str:
        calls.append(url)
        return "<title>Before you continue</title><p>unusual traffic from your computer</p>"

    result = asyncio.run(GoogleHotelsDirectSource(fetch=blocked).search(Q))
    assert result.run_report.status == "degraded" and result.items == []
    assert result.run_report.errors == ["blocked:unusual traffic"] and len(calls) == 1

    def boom(url: str, timeout: float) -> str:
        raise RuntimeError("HTTP 503")

    result = asyncio.run(GoogleHotelsDirectSource(fetch=boom).search(Q))
    assert result.run_report.status == "failed" and "HTTP 503" in result.run_report.errors[0]


def test_pipeline_panel_shows_both_google_hotels_runs() -> None:
    from conferge.integration import travel_cache
    from conferge.integration.pipeline_view import build_rows

    travel = travel_cache.load()
    rows = build_rows([], travel, {"stays": False, "flights": False})
    by = {r["provider"]: r for r in rows}
    assert by["google_hotels"]["kind"] == "brightdata" and by["google_hotels"]["records"] == 0
    assert "no_peers" in by["google_hotels"]["reason"]
    assert by["google_hotels_direct"]["kind"] == "direct" and by["google_hotels_direct"]["records"] == 0
    assert by["google_hotels_direct"]["status"] == "degraded"
