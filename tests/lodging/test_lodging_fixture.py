from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from conferge.lodging import FIXTURE_PATH, LodgingError, fixture_envelope, load_fixture

LATER = datetime(2026, 10, 24, 16, 40, tzinfo=timezone.utc)  # 7 min after capture


def test_fixture_requires_explicit_opt_in():
    with pytest.raises(LodgingError):
        load_fixture()
    with pytest.raises(LodgingError):
        fixture_envelope()


def test_fixture_is_labelled_and_varied():
    raw = json.loads(Path(FIXTURE_PATH).read_text(encoding="utf-8"))
    providers = [r["provider"] for r in raw["records"]]
    assert providers.count("booking") == 8 and providers.count("google_hotels") == 4
    assert providers.count("airbnb") == 3 and raw["source_mode"] == "fixture"
    for r in raw["records"]:
        if r["provider"] != "airbnb":
            assert r["fictional"] is True
    res = load_fixture(explicit_opt_in=True)
    assert res.run_report.source_mode == "fixture"
    assert all(i.source_mode == "fixture" for i in res.items)
    assert "FIXTURE" in res.run_report.warnings[0]


def test_fixture_normalizes_with_price_truth():
    env = fixture_envelope(explicit_opt_in=True, clock=lambda: LATER)
    assert env.source_mode == "fixture" and len(env.items) == 15
    statuses = {s.price_status for s in env.items}
    assert "verified_bookable" not in statuses
    assert {"quoted_total", "indicative", "unknown", "unavailable"} <= statuses
    for s in env.items:
        assert s.evidence[0].source_mode == "fixture" and s.evidence[0].collected_at
        assert s.check_in.isoformat() == "2026-10-27" and s.adults == 1
        if s.total_price is not None:
            assert s.total_price > 0 and s.currency == "USD"
        if s.provider == "airbnb":
            assert s.venue.coordinate_precision == "approximate" and s.taxes is None
    groups = {}
    for s in env.items:
        groups.setdefault(s.dedup_group, []).append(s.provider)
    assert sorted(max(groups.values(), key=len)) == ["booking", "google_hotels"]
    zero = next(s for s in env.items if s.id == "booking:fixture-bk-5")
    assert zero.total_price is None and zero.price_status == "unknown"
