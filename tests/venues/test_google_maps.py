"""Google Maps venues: inputs, matching, no-overwrite graph writes, travel coordinates, pipeline row."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any

from conferge.agents.antifomo.models import Constraints
from conferge.agents.antifomo.travel import travel_minutes
from conferge.core.schemas import Event, SourceEvidence, Venue
from conferge.core.store import GraphStore
from conferge.integration.pipeline_view import row
from conferge.venues import google_maps as gm

CONF = {"venue_name": "Fort Mason Center", "address": "2 Marina Blvd", "city": "San Francisco",
        "latitude": 37.806, "longitude": -122.432}
T0 = datetime(2026, 10, 28, 18, 0, tzinfo=timezone.utc)


def _event(eid: str, name: str, lat: float | None = None, lng: float | None = None,
           kind: str = "party") -> dict[str, Any]:
    return {"id": eid, "event_type": kind, "conference_relation": "candidate",
            "venue": {"name": name, "address": None, "city": "San Francisco", "latitude": lat, "longitude": lng}}


def test_plan_venues_fort_mason_first_dedup_by_name_and_city_and_capped() -> None:
    events = [_event("a", "Sightglass Coffee", 37.77, -122.40), _event("b", "sightglass coffee"),
              _event("s", "Fort Mason Center", kind="session")]
    events += [_event(f"e{i}", f"Venue {i}") for i in range(20)]
    plan = {"days": [{"items": [{"event_id": e["id"]} for e in events]}]}
    venues = gm.plan_venues(plan, events, CONF)
    assert venues[0]["query_name"] == "Fort Mason Center"
    assert len(venues) == gm.MAX_VENUES
    sight = next(v for v in venues if v["query_name"] == "Sightglass Coffee")
    assert sight["event_ids"] == ["a", "b"]
    inputs = gm.inputs_for(venues, CONF)
    assert inputs[1] == {"keyword": "Sightglass Coffee San Francisco", "lat": 37.77, "long": -122.40,
                         "zoom_level": gm.ZOOM, "country": "US"}
    assert inputs[2]["zoom_level"] == gm.CITY_ZOOM and inputs[2]["lat"] == CONF["latitude"]


def test_chain_branches_are_never_guessed() -> None:
    venues = gm.plan_venues({"days": [{"items": [{"event_id": "a"}, {"event_id": "b"}]}]},
                            [_event("a", "Equator Coffee"), _event("b", "Sightglass Coffee", 37.777, -122.4084)], CONF)
    records = [{"name": "Equator Coffees", "address": a, "latitude": lat, "longitude": lng}
               for a, lat, lng in (("1201 Bridgeway, Sausalito, CA", 37.85, -122.48),
                                   ("222 2nd St, San Francisco, CA", 37.786, -122.397),
                                   ("2 Marina Blvd, San Francisco, CA", 37.806, -122.432))]
    records += [{"name": "Sightglass Coffee", "address": a, "latitude": lat, "longitude": lng}
                for a, lat, lng in (("270 7th St, San Francisco, CA", 37.7770356, -122.4084543),
                                    ("3014 20th St, San Francisco, CA", 37.759, -122.410))]
    out = {e["query_name"]: e for e in gm.match(venues, records, snapshot_id="s", collected_at=T0.isoformat())}
    assert not out["Equator Coffee"]["found"] and out["Equator Coffee"]["match_reason"].startswith("ambiguous")
    assert out["Sightglass Coffee"]["address"].startswith("270 7th St")


def test_match_uses_aliases_and_leaves_unknown_venues_null() -> None:
    venues = gm.plan_venues({"days": [{"items": [{"event_id": "a"}, {"event_id": "b"}]}]},
                            [_event("a", "Sightglass Coffee"), _event("b", "Nowhere Hall")], CONF)
    records = [
        {"title": "Fort Mason Center for Arts & Culture", "full_address": "2 Marina Blvd, San Francisco, CA",
         "lat": "37.8065", "lon": "-122.4320", "totalScore": "4.7", "reviewsCount": "3.1K",
         "placeId": "pm1", "input": {"keyword": "Fort Mason Center San Francisco"}},
        {"name": "Sightglass Coffee", "address": "270 7th St, San Francisco, CA", "latitude": 37.777, "longitude": -122.408,
         "rating": 4.5, "reviews_count": 1200, "website": "https://sightglass.com", "place_id": "sg1",
         "input": {"keyword": "Sightglass Coffee San Francisco"}},
        {"error": "dead_page", "error_code": "dead_page"},
    ]
    out = {e["query_name"]: e for e in gm.match(venues, records, snapshot_id="sd_x", collected_at=T0.isoformat())}
    fm = out["Fort Mason Center"]
    assert fm["found"] and fm["lat"] == 37.8065 and fm["reviews_count"] == 3100 and fm["place_id"] == "pm1"
    assert out["Sightglass Coffee"]["website"] == "https://sightglass.com"
    nowhere = out["Nowhere Hall"]
    assert not nowhere["found"] and all(nowhere[k] is None for k in gm.PLACE_FIELDS)
    assert nowhere["provider"] == gm.PROVIDER and nowhere["dataset_id"] == gm.DATASET_ID


class _Graph:
    def __init__(self, existing: dict[str, Any]) -> None:
        self.existing, self.writes = existing, []

    def query(self, q: str, params: dict[str, Any] | None = None) -> Any:
        if q.startswith("MATCH (v:Venue"):
            return SimpleNamespace(result_set=[[self.existing]] if self.existing else [])
        self.writes.append((q, params))
        return SimpleNamespace(result_set=[])


def test_graph_write_never_overwrites_a_non_null_property() -> None:
    graph = _Graph({"name": "Fort Mason Center", "latitude": 37.806, "longitude": -122.432, "address": None})
    entry = {"venue_id": "venue:fort-mason-center-san-francisco", "found": True, "name": "Fort Mason Center",
             "address": "2 Marina Blvd", "lat": 37.8065, "lng": -122.432, "rating": 4.7, "reviews_count": 3100,
             "website": None, "place_id": "pm1", "city": "San Francisco", "dataset_id": gm.DATASET_ID,
             "snapshot_id": "sd_x", "collected_at": T0.isoformat()}
    assert gm.write_graph(GraphStore(graph), [entry, {**entry, "venue_id": None, "found": False}]) == {
        "written": 1, "skipped_not_found": 1}
    (q, params), = graph.writes
    assert "MERGE (n:Venue" in q
    values = set(params.values())
    assert 37.8065 in values and "2 Marina Blvd" in values and "pm1" in values
    assert "latitude = " not in q.replace("google_maps_latitude", "")  # fixture latitude kept


def test_google_coordinates_drive_travel_times_and_are_labelled() -> None:
    venue = Venue(name="Sightglass Coffee", city="San Francisco", latitude=37.70, longitude=-122.50)
    a = Event(id="a", title="A", start_at=T0, end_at=T0 + timedelta(hours=1), venue=venue,
              evidence=[SourceEvidence(provider="luma", source_mode="fixture")])
    b = Event(id="b", title="B", start_at=T0 + timedelta(hours=2), end_at=T0 + timedelta(hours=3),
              venue=Venue(name="Fort Mason Center", city="San Francisco", latitude=37.8065, longitude=-122.432,
                          coordinate_precision="exact"))
    before, basis_before = travel_minutes(a, b, Constraints())
    assert basis_before == "unknown_default"  # fixture point of unknown precision is not used
    entry = {"found": True, "lat": 37.777, "lng": -122.408, "event_ids": ["a"], "place_id": "sg1",
             "snapshot_id": "sd_x", "collected_at": T0.isoformat()}
    (a2, b2), changed = gm.apply_to_events([a, b], [entry])
    assert changed == 1 and b2 is b
    assert (a2.venue.latitude, a2.venue.longitude) == (37.777, -122.408)
    assert a2.evidence[-1].provider == gm.PROVIDER and a2.evidence[-1].raw_ref == "sd_x"
    after, basis = travel_minutes(a2, b2, Constraints())
    assert basis == "haversine"


def test_pipeline_row_is_a_bright_data_dataset_run() -> None:
    cache = {"run": {"snapshot_id": "sd_x", "status": "ready", "records": 12,
                     "started_at": T0.isoformat(), "finished_at": (T0 + timedelta(seconds=40)).isoformat()},
             "venues": [{"found": True, "collected_at": T0.isoformat()}, {"found": False, "collected_at": T0.isoformat()}]}
    r = row("venues", gm.run_report(cache))
    assert (r["kind"], r["brightdata_api"], r["records"], r["status"]) == ("brightdata", "dataset", 1, "degraded")
    timed_out = {**cache, "run": {**cache["run"], "status": "running"}}
    assert row("venues", gm.run_report(timed_out))["status"] == "failed"
