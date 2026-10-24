from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

import pytest

from conferge.travel.places import EMBARCADERO, FORT_MASON, SFO
from conferge.travel.providers.base import RouteProvider
from conferge.travel.providers.walk import HaversineWalkProvider, haversine_m


def test_protocol() -> None:
    assert isinstance(HaversineWalkProvider(), RouteProvider)


def test_haversine_sfo_fort_mason() -> None:
    d = haversine_m(SFO, FORT_MASON)
    assert 20_000 <= d <= 22_000
    assert haversine_m(FORT_MASON, SFO) == pytest.approx(d)
    assert haversine_m(SFO, SFO) == 0


async def test_walk_leg_deterministic() -> None:
    provider = HaversineWalkProvider()
    a = await provider.route(EMBARCADERO, FORT_MASON, mode="walk")
    b = await provider.route(EMBARCADERO, FORT_MASON, mode="walk")
    (leg,) = a.legs
    assert leg.distance_m == b.legs[0].distance_m
    assert leg.duration_minutes == b.legs[0].duration_minutes
    expected_m = haversine_m(EMBARCADERO, FORT_MASON) * 1.3
    assert leg.distance_m == round(expected_m)
    assert leg.duration_minutes == math.ceil(expected_m / 1000 / 5.0 * 60)
    assert leg.duration_status == "estimate"
    assert leg.price.amount == "0" and leg.price.status == "exact"
    assert leg.provider == "haversine" and leg.source_mode == "live"
    assert leg.warnings == ["straight-line estimate x1.3 detour at 5 km/h, not a routed path"]
    assert a.run_report.status == "ok"
    assert a.run_report.termination == "not_applicable"


async def test_arrival_from_depart_at() -> None:
    depart = datetime(2026, 10, 28, 15, 0, tzinfo=timezone.utc)
    out = await HaversineWalkProvider().route(
        EMBARCADERO, FORT_MASON, mode="walk", depart_at=depart
    )
    (leg,) = out.legs
    assert leg.arrival_local - leg.departure_local == timedelta(minutes=leg.duration_minutes)


async def test_rejects_other_modes() -> None:
    out = await HaversineWalkProvider().route(SFO, FORT_MASON, mode="drive")
    assert out.legs == [] and out.run_report.status == "failed"
