"""Anti-FOMO step of the demo: top skipped events with a category and what skipping gains."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from conferge.api import logic
from conferge.api.app import create_app
from conferge.api.data import load_fixture
from conferge.core.schemas import Event, Venue

T0 = datetime(2026, 10, 28, 18, 0, tzinfo=timezone.utc)


def _event(eid: str, start: int, minutes: int, lat: float) -> Event:
    return Event(id=eid, title=eid.upper(), start_at=T0 + timedelta(minutes=start),
                 end_at=T0 + timedelta(minutes=start + minutes),
                 venue=Venue(name=f"v-{eid}", latitude=lat, longitude=-122.42))


def _data():  # type: ignore[no-untyped-def]
    data = load_fixture()
    data.events[:] = [
        _event("keep", 0, 60, 37.80), _event("overlap", 30, 60, 37.80),
        _event("far", 70, 60, 37.70), _event("dull", 300, 90, 37.80),
        _event("planned", 500, 30, 37.80),
    ]
    return data


def _decisions() -> list[dict]:
    return [
        {"type": "plan_item", "event_id": "keep", "title": "KEEP", "utility": 80.0, "targets_confirmed": []},
        {"type": "rejected", "event_id": "overlap", "title": "OVERLAP", "code": "conflict",
         "reason": "overlaps 'KEEP'", "blocking_event_id": "keep", "utility": 50.0},
        {"type": "rejected", "event_id": "far", "title": "FAR", "code": "conflict",
         "reason": "overlaps 'KEEP' incl. 30 min travel", "blocking_event_id": "keep", "utility": 40.0},
        {"type": "rejected", "event_id": "dull", "title": "DULL", "code": "low_utility",
         "reason": "no goal alignment (utility 0)", "utility": 0.0},
        {"type": "rejected", "event_id": "planned", "title": "PLANNED", "code": "low_utility",
         "reason": "x", "utility": 90.0},
    ]


def test_skips_cover_each_reason_with_a_gain_and_skip_planned_events() -> None:
    skips = logic.antifomo_skips(_decisions(), _data(), planned={"planned"})
    assert [(s["event_id"], s["category"]) for s in skips] == [
        ("overlap", "time_conflict"), ("far", "travel"), ("dull", "low_score")]
    assert {s["category_label"] for s in skips} == {"conflit horaire", "trajet trop long", "score faible"}
    assert skips[0]["gain"] == "you keep 'KEEP' (+30 utility)"
    assert skips[2]["gain"].startswith("90 min freed")


def test_antifomo_endpoint_calls_the_agent() -> None:
    client = TestClient(create_app(graph_probe=False))
    body = client.get("/api/v1/antifomo").json()
    assert body["computed_by"] == "antifomo"
    planned = {i["event_id"] for d in client.get("/api/v1/plan").json()["plan"]["days"] for i in d["items"]}
    assert len(body["skips"]) <= 4
    for skip in body["skips"]:
        assert skip["event_id"] not in planned
        assert skip["category_label"] and skip["reason"] and skip["gain"]


def test_plan_keeps_only_trip_days() -> None:
    data = _data()
    data.user["depart_date"], data.user["return_date"] = "2026-10-28", "2026-10-28"
    late = _event("late", 60 * 24 * 30, 60, 37.80)
    data.events.append(late)
    plan = logic.build_plan(data, [], [])
    planned = {i["event_id"] for d in plan["days"] for i in d["items"]}
    assert "late" not in planned and "keep" in planned
    assert {"event_id": "late", "title": "LATE", "reason": "outside_trip"} in plan["excluded"]


def test_in_person_event_abroad_at_night_is_skipped_as_outside_hours() -> None:
    # Eventbrite Singapore event: 18:00 +08:00 is 03:00 in San Francisco; the source value stays as is.
    data = _data()
    sgt = timezone(timedelta(hours=8))
    data.events.append(Event(
        id="sg", title="SG", timezone="Asia/Singapore", venue=Venue(name="Kingston International College"),
        start_at=datetime(2026, 10, 28, 18, 0, tzinfo=sgt), end_at=datetime(2026, 10, 28, 21, 0, tzinfo=sgt)))
    plan = logic.build_plan(data, [], [])
    assert "sg" not in {i["event_id"] for d in plan["days"] for i in d["items"]}
    excluded = next(x for x in plan["excluded"] if x["event_id"] == "sg")
    assert excluded["reason"] == "outside_hours"
    assert "03:00 America/Los_Angeles in person in Asia/Singapore (18:00 local)" in excluded["detail"]
    assert data.events[-1].start_at == datetime(2026, 10, 28, 18, 0, tzinfo=sgt)
    skips = logic.antifomo_skips(_decisions(), data, planned={"planned"})
    assert skips[0]["event_id"] == "sg" and skips[0]["category_label"] == "hors plage horaire"
    assert skips[0]["timezone"] == "Asia/Singapore"


def test_online_or_daytime_events_are_kept_and_abroad_daytime_is_other_timezone() -> None:
    tz = "America/Los_Angeles"
    pdt = timezone(timedelta(hours=-7))
    night = datetime(2026, 10, 28, 3, 0, tzinfo=pdt)
    online = Event(id="o", title="O", start_at=night, venue=Venue(name="Online"))
    assert logic.off_hours_reason(online, tz) is None
    local_night = Event(id="n", title="N", start_at=night, timezone=tz)
    assert logic.off_hours_reason(local_night, tz)[0] == "outside_hours"  # type: ignore[index]
    day_abroad = Event(id="p", title="P", timezone="Europe/Paris",
                       start_at=datetime(2026, 10, 28, 18, 0, tzinfo=timezone(timedelta(hours=1))))
    assert logic.off_hours_reason(day_abroad, tz)[0] == "other_timezone"  # type: ignore[index]
    assert logic.off_hours_reason(Event(id="d", title="D", start_at=night.replace(hour=9), timezone=tz), tz) is None
