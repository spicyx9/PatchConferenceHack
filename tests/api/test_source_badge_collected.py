"""Audit gap 4: stay and flight cards say Cached/Live/Fixture with the collection time."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

from conferge.api.provenance import source_of
from conferge.core.schemas import SourceEvidence

APP = Path(__file__).resolve().parents[2] / "static" / "app.js"


def _fn(name: str) -> str:
    src = APP.read_text(encoding="utf-8")
    start = src.index(f"function {name}(")
    depth, i = 0, src.index("{", start)
    while True:
        depth += {"{": 1, "}": -1}.get(src[i], 0)
        i += 1
        if depth == 0:
            return src[start:i]


def test_source_carries_collected_at() -> None:
    ev = SourceEvidence(provider="booking", source_mode="cached", raw_ref="sd_x",
                        source_url="https://www.booking.com/hotel/x.html",
                        collected_at=datetime(2026, 10, 24, 18, 41, 14, tzinfo=timezone.utc))
    assert source_of([ev])["collected_at"] == "2026-10-24T18:41:14+00:00"
    assert source_of([])["collected_at"] is None


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_source_badge_never_empty_and_shows_local_time() -> None:
    script = "\n".join([
        'var EVENT_TZ = "America/Los_Angeles";',
        "function esc(s) { return String(s); }",
        _fn("sourceModeBadge"), _fn("fmtClock"), _fn("sourceBadge"), _fn("sourceApiBadge"),
        _fn("recordMode"),
        "function sourceApiText(s) { return s.label; }",
        'console.log(sourceBadge("cached", "2026-10-24T18:41:14+00:00"));',
        'console.log(sourceBadge("live", "2026-10-24T16:02:00+00:00"));',
        'console.log(sourceBadge("fixture", null));',
        'console.log(sourceApiBadge({tier: 0, label: "Bright Data dataset", collected_at: "2026-10-24T18:41:14+00:00"}));',
        'console.log(recordMode({evidence: [{source_mode: "cached"}]}));',
    ])
    out = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True).stdout
    cached, live, fixture, api, flight_mode = out.splitlines()
    assert re.search(r">Cached · 11:41 AM<", cached)  # 18:41 UTC = 11:41 AM PDT
    assert "collected_at 2026-10-24T18:41:14+00:00" in cached
    assert ">Live · 9:02 AM<" in live
    assert ">Fixture<" in fixture
    assert "collected_at: 2026-10-24T18:41:14+00:00" in api
    assert flight_mode == "cached"  # flight offers carry the mode in their evidence only


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_cards_render_the_mode_badge_outside_details() -> None:
    script = "\n".join([
        "var window = {}; var location = {origin: 'https://example.test'};",
        APP.with_name("travel-cards.js").read_text(encoding="utf-8"),
        "var badge = '<b id=collection-badge>Cached · 11:41 AM</b>';",
        "var flight = window.TravelCards.flight({slices: []}, '<p>Source</p>', badge);",
        "var stay = window.TravelCards.stay({check_in: '2026-10-27', check_out: '2026-10-30', "
        "adults: 1, rooms: 1}, '<details>Source</details>', badge);",
        "console.log(JSON.stringify([flight, stay]));",
    ])
    result = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True)
    for rendered, column in zip(json.loads(result.stdout), ("fare-price", "stay-price"), strict=True):
        assert rendered.index(column) < rendered.index("collection-badge")
        assert rendered.index("collection-badge") < rendered.index("<details")
        assert "Cached · 11:41 AM" in rendered
