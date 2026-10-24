"""fli (Google Flights) secondary source: never guessed prices, ranked behind Web Unlocker."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace as NS

from conferge.api.provenance import source_of
from conferge.core.schemas import FlightOffer
from conferge.flights import fli_provider as fli
from conferge.flights.round_trip_total import display
from conferge.integration.pipeline_view import fli_rows
from conferge.integration.stays_flights import pick_flights

AT = datetime(2026, 10, 24, 20, 0, tzinfo=timezone.utc)
URL = fli.search_url("JFK", "SFO", datetime(2026, 10, 27).date(), datetime(2026, 10, 30).date())


def _leg(o: str, d: str, dep: str, arr: str) -> NS:
    return NS(airline=NS(name="B6"), flight_number="123", departure_airport=NS(name=o),
              arrival_airport=NS(name=d), departure_datetime=datetime.fromisoformat(dep),
              arrival_datetime=datetime.fromisoformat(arr), duration=380, operating_airline=None,
              aircraft=None)


def _pair(out_price: float | None, total: float | None) -> tuple[NS, NS]:
    out = NS(legs=[_leg("JFK", "SFO", "2026-10-27T10:00:00-04:00", "2026-10-27T13:44:00-07:00")],
             price=out_price, currency="USD", duration=464)
    back = NS(legs=[_leg("SFO", "JFK", "2026-10-30T08:00:00-07:00", "2026-10-30T16:30:00-04:00")],
              price=total, currency="USD", duration=330)
    return out, back


def test_round_trip_total_is_quoted_total() -> None:
    offer = fli.offer_from_pair(*_pair(300.0, 716.0), url=URL, collected_at=AT)
    assert offer.trip_type == "round_trip" and offer.total_price == "716"
    assert offer.price_scope == "total_all_passengers"
    assert fli.display_status(offer) == "quoted_total" and display(offer)["price_status"] == "quoted_total"
    ev = offer.evidence[0]
    assert ev.provider == "google_flights_fli" and str(ev.source_url) == URL and ev.collected_at == AT


def test_outbound_only_price_is_indicative_and_never_used_as_total() -> None:
    offer = fli.offer_from_pair(*_pair(300.0, None), url=URL, collected_at=AT)
    assert offer.total_price is None and offer.raw_price_text == "outbound row price 300.00 USD"
    assert fli.display_status(offer) == "indicative"
    none = fli.offer_from_pair(*_pair(None, None), url=URL, collected_at=AT)
    assert none.total_price is None and none.raw_price_text is None
    assert fli.display_status(none) == "unknown"


def test_fli_ranks_behind_web_unlocker_even_when_cheaper() -> None:
    cache = json.loads(Path("data/cache/flights.json").read_text())
    unlocker = [FlightOffer.model_validate(r["record"]) for r in cache["records"]][:3]
    cheap = fli.offer_from_pair(*_pair(50.0, 99.0), url=URL, collected_at=AT)
    src = source_of(cheap.evidence)
    assert (src["provider"], src["api"], src["tier"]) == ("fli", "fallback", 2)
    picked = pick_flights([cheap, *unlocker])
    assert picked and all(source_of(o.evidence)["provider"] == "brightdata" for o in picked)


def test_failure_is_reported_never_invented(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    def rejected(*a, **k):  # type: ignore[no-untyped-def]
        return [], fli.empty_reason(')]}\'\n[["wrb.fr",null,null,null,null,[13]]]')

    monkeypatch.setattr(fli, "_search", rejected)
    offers, rep = asyncio.run(fli.search_round_trip())
    assert offers == [] and rep.status == "failed" and rep.provider == "google_flights_fli"
    assert rep.errors == ["Google answered without flight data (RPC error 13: request rejected)"]

    def slow(*a, **k):  # type: ignore[no-untyped-def]
        import time
        time.sleep(1)
        return [], None

    monkeypatch.setattr(fli, "_search", slow)
    offers, rep = asyncio.run(fli.search_round_trip(timeout_s=0.1))
    assert offers == [] and rep.errors == ["fli timeout after 0s"]


def test_panel_row_reads_the_last_fli_run(tmp_path: Path) -> None:
    run = {"provider": "google_flights_fli", "run_at": AT.isoformat(), "status": "failed", "records": 0,
           "errors": ["Google answered without flight data (RPC error 13: request rejected)"],
           "google_flights": {"dataset": "pending", "unlocker": 34, "fli": 0}}
    path = tmp_path / "fli_run.json"
    path.write_text(json.dumps(run))
    (row,) = fli_rows(path)
    assert row["provider"] == "google_flights_fli" and row["status"] == "failed" and row["records"] == 0
    assert row["reason"].startswith("Google Flights: Bright Data dataset pending, Web Unlocker 34, fli 0")
    assert "RPC error 13" in row["reason"]
    assert fli_rows(tmp_path / "absent.json") == []
