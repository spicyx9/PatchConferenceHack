import pytest

from conferge.core.store import GraphStore
from conferge.travel.fixture import FixtureNotRequested, load_fixture, relabel_as_fixture
from conferge.travel.graph import write_plans
from conferge.travel.map import map_features
from conferge.travel.models import Price, RouteLeg, RoutePlan, utcnow
from conferge.travel.places import EMBARCADERO, FORT_MASON, SFO
from conferge.travel.routes import make_option


class RecordingGraph:
    def __init__(self):
        self.queries = []

    def query(self, q, params=None):
        self.queries.append((q, params or {}))


def _plan() -> RoutePlan:
    now = utcnow()
    known = RouteLeg(from_place=SFO, to_place=EMBARCADERO, mode="bart", duration_minutes=31,
                     duration_status="scheduled", provider="bart", source_mode="live",
                     collected_at=now,
                     price=Price(amount="11.80", currency="USD", status="exact"))
    unknown = RouteLeg(from_place=EMBARCADERO, to_place=FORT_MASON, mode="muni",
                       provider="none", source_mode="live", collected_at=now)
    return RoutePlan(origin=SFO, destination=FORT_MASON, source_mode="live", status="ok",
                     options=[make_option("o1", "BART then Muni", [known, unknown])])


def test_option_with_unknown_leg_is_incomplete():
    opt = _plan().options[0]
    assert not opt.complete and opt.total_duration_minutes is None
    assert opt.total_price.status == "unknown" and opt.total_price.amount is None


def test_map_features_points_and_straight_segments():
    fc = map_features([_plan()])
    kinds = [f["geometry"]["type"] for f in fc["features"]]
    assert kinds.count("Point") == 3 and kinds.count("LineString") == 2
    line = next(f for f in fc["features"] if f["geometry"]["type"] == "LineString")
    assert line["properties"]["geometry"] == "straight_segment"
    assert line["geometry"]["coordinates"][0] == [SFO.longitude, SFO.latitude]


def test_graph_writes_only_known_durations_via_store():
    graph = RecordingGraph()
    assert write_plans(GraphStore(graph), [_plan()]) == 1
    edge = [q for q in graph.queries if "NEAR" in q[0]]
    assert len(edge) == 1 and 31 in edge[0][1].values()
    assert not any("muni_minutes" in str(q) for q in graph.queries)


def test_fixture_requires_opt_in_and_relabels(tmp_path):
    with pytest.raises(FixtureNotRequested):
        load_fixture()
    data = relabel_as_fixture(_plan())
    assert data["source_mode"] == "fixture"
    assert all(leg["source_mode"] == "fixture" for leg in data["options"][0]["legs"])
    path = tmp_path / "t.json"
    import json
    path.write_text(json.dumps({"plans": [data]}))
    plans = load_fixture(path, explicit_opt_in=True)
    assert plans[0].options[0].legs[0].warnings[-1].startswith("FIXTURE")
