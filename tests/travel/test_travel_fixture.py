import json

from conferge.travel.fixture import FIXTURE_PATH, load_fixture
from conferge.travel.providers.base import RouteProvider
from conferge.travel.routes import default_planner


def test_committed_fixture_parses_and_is_labelled():
    raw = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    assert raw["source_mode"] == "fixture" and "Not live" in raw["note"]
    plans = load_fixture(explicit_opt_in=True)
    assert plans and all(p.source_mode == "fixture" for p in plans)
    for plan in plans:
        assert all(r.source_mode == "fixture" for r in plan.reports)
        for option in plan.options:
            for leg in option.legs:
                assert leg.source_mode == "fixture" and leg.collected_at.tzinfo
                assert any(w.startswith("FIXTURE") for w in leg.warnings)
                if leg.price.amount is None:
                    assert leg.price.status == "unknown"
    text = FIXTURE_PATH.read_text(encoding="utf-8")
    assert "key=" not in text and "MW9S" not in text


async def test_default_planner_wires_protocol_providers():
    planner = default_planner()
    try:
        for p in (planner.bart, planner.walk, planner.walk_fallback, planner.drive,
                  planner.rideshare):
            assert isinstance(p, RouteProvider)
    finally:
        await planner.aclose()
