"""ROI panel (w17): /roi moves after a /met, unknown spend stays null, the HTML carries the 4 ids."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from conferge.api.app import STATIC_DIR, create_app
from conferge.api.providers import Providers

ROI_IDS = ("roi-spend", "roi-meetings", "roi-qualified", "roi-opportunities")


@pytest.fixture()
def client() -> TestClient:
    return TestClient(create_app(found=Providers(), graph_probe=False))


def test_roi_moves_after_met(client: TestClient) -> None:
    before = client.get("/api/v1/roi").json()
    assert before["meetings"] == 0 and before["qualified_contacts"] == 0

    top = client.get("/api/v1/people", params={"limit": 1}).json()["items"][0]["person"]["id"]
    assert client.post("/api/v1/met", json={"person_id": top, "note": "roi test"}).status_code == 200

    after = client.get("/api/v1/roi").json()
    assert after["meetings"] == before["meetings"] + 1
    assert after["qualified_contacts"] >= before["qualified_contacts"]
    # The person met leaves the open opportunities: the figure can only go down.
    assert after["opportunities"] <= before["opportunities"]


def test_roi_unknown_spend_is_null_with_note(client: TestClient) -> None:
    roi = client.get("/api/v1/roi").json()
    # Fixture flights and stays carry no price: the spend is unknown, never 0.
    assert roi["spend_usd"] is None
    assert roi["spend_note"] and "unknown" in roi["spend_note"]
    assert '"spend_usd":0' not in client.get("/api/v1/roi").text


def test_index_html_has_the_four_roi_ids() -> None:
    html = Path(STATIC_DIR, "index.html").read_text(encoding="utf-8")
    for element_id in ROI_IDS:
        assert html.count(f'id="{element_id}"') == 1, element_id
    js = Path(STATIC_DIR, "app.js").read_text(encoding="utf-8")
    for element_id in ROI_IDS:
        assert f'"{element_id}"' in js, element_id
    # The unknown state is spelled out in the markup, no 0 placeholder.
    assert 'id="roi-spend" class="value unknown">unknown<' in html
