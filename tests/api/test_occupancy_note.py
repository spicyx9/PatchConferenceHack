from __future__ import annotations

from fastapi.testclient import TestClient

from conferge.api.app import create_app
from conferge.api.logic import OCCUPANCY_NOTE
from conferge.api.providers import Providers
from conferge.integration import travel_cache
from conferge.integration.assemble import assemble
from conferge.integration.sources import fixture_slices

NOTE = "Stay quoted for 2 adults · flight for 1 adult (collection settings)"


def test_trip_total_and_roi_carry_the_occupancy_note_without_changing_amounts() -> None:
    assert OCCUPANCY_NOTE == NOTE
    demo = assemble(fixture_slices(), travel_cache.load()).demo
    client = TestClient(create_app(data=demo, found=Providers(), graph_probe=False))
    budget = client.get("/api/v1/travel").json()["budget"]
    roi = client.get("/api/v1/roi").json()
    assert budget["occupancy_note"] == NOTE and roi["occupancy_note"] == NOTE
    assert budget["flights_usd"] == "413"  # amounts unchanged
    js = client.get("/static/app.js").text
    assert js.count("occupancy_note") >= 3  # Travel budget, ROI note, known-costs note
