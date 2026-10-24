"""Same site = 5 min room change; the 20 min default only between distinct sites without coordinates."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from conferge.agents.antifomo.models import Constraints
from conferge.agents.antifomo.travel import site_name, travel_minutes
from conferge.core.schemas import Event, SourceEvidence, Venue

T0 = datetime(2026, 10, 28, 17, 0, tzinfo=timezone.utc)
C = Constraints(conference_site=site_name("Fort Mason Center"))


def _ev(eid: str, venue: str, *, official: bool = False, lat: float | None = None, lng: float | None = None) -> Event:
    return Event(id=eid, title=eid, start_at=T0, end_at=T0 + timedelta(hours=1),
                 conference_id="github-universe-2026" if official else None,
                 conference_relation="official" if official else "candidate",
                 relation_evidence=["official catalog"] if official else [],
                 evidence=[SourceEvidence(provider="rainfocus", source_mode="fixture")] if official else [],
                 venue=Venue(name=venue, latitude=lat, longitude=lng,
                             coordinate_precision="exact" if lat is not None else "unknown"))


def test_site_names() -> None:
    assert site_name("Fort Mason Building C, Founders Inc., 3rd Floor") == "fort mason"
    assert site_name("Fort Mason Center") == "fort mason"
    assert site_name("Gateway Pavilion, Level 2") == site_name("Gateway Pavilion") == "gateway"
    assert site_name("Main Stage @ Festival Pavilion") == "festival"


def test_official_sessions_in_different_pavilions_are_the_same_site() -> None:
    a, b = _ev("a", "Festival Pavilion", official=True), _ev("b", "Firehouse", official=True)
    assert travel_minutes(a, b, C) == (5, "same_venue")
    side = _ev("c", "Fort Mason Center")  # a side event at the conference venue
    assert travel_minutes(a, side, C) == (5, "same_venue")
    assert travel_minutes(_ev("d", "Fort Mason Building B, 3rd Floor"), side, C) == (5, "same_venue")


def test_coordinates_within_300_m_are_the_same_site() -> None:
    a = _ev("a", "Place A", lat=37.8000, lng=-122.4300)
    near = _ev("b", "Place B", lat=37.8020, lng=-122.4300)  # about 220 m
    far = _ev("c", "Place C", lat=37.7800, lng=-122.4300)   # about 2.2 km
    assert travel_minutes(a, near, C) == (5, "same_venue")
    assert travel_minutes(a, far, C)[1] == "haversine"


def test_default_only_between_distinct_sites_without_coordinates() -> None:
    assert travel_minutes(_ev("a", "Sightglass Coffee"), _ev("b", "Equator Coffee"), C) == (20, "unknown_default")


def test_plan_payload_labels_the_default() -> None:
    from conferge.api import logic
    from conferge.api.data import load_fixture

    data = load_fixture()
    t = T0
    data.events[:] = [
        _ev("x", "Sightglass Coffee").model_copy(update={"start_at": t, "end_at": t + timedelta(hours=1)}),
        _ev("y", "Equator Coffee").model_copy(update={"start_at": t + timedelta(hours=2),
                                                     "end_at": t + timedelta(hours=3)}),
    ]
    plan = logic.build_plan(data, [], [], scores={"x": 2.0, "y": 1.0})
    items = [i for d in plan["days"] for i in d["items"]]
    assert items[0]["travel_from_previous"] is None
    assert items[1]["travel_from_previous"] == {"minutes": 20, "basis": "default"}
