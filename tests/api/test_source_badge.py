"""Rehearsal bug 6: the provenance badge said "Mixed sources" as soon as stays or flights were live.

Decision: the badge carries the conference data's mode (events, people, conference, companies)
and names travel apart when it differs: "Sample data, live travel". The per-domain rows of the
sources dialog keep the detail; "Mixed sources" stays for core domains that disagree.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from conferge.api import logic
from conferge.api.app import create_app
from conferge.api.data import DomainSlice, load_fixture
from conferge.api.providers import Providers

T = datetime(2026, 10, 24, 9, 0, tzinfo=timezone.utc)


def _domains(**modes: str) -> dict[str, DomainSlice]:
    return {name: DomainSlice(mode, "ok", T) for name, mode in modes.items()}


def test_snapshot_with_live_travel_reads_sample_data_live_travel() -> None:
    badge = logic.source_badge(_domains(conference="fixture", events="fixture", people="fixture",
                                        companies="fixture", stays="live", flights="live"))
    assert badge == {"mode": "fixture", "core_mode": "fixture", "travel_mode": "live",
                     "label": "Sample data, live travel"}


def test_snapshot_with_cached_travel_and_all_fixture_and_all_live() -> None:
    cached = logic.source_badge(_domains(events="fixture", people="fixture", stays="cached", flights="cached"))
    assert cached["label"] == "Sample data, cached travel" and cached["core_mode"] == "fixture"
    fixture = logic.source_badge(_domains(events="fixture", people="fixture", stays="fixture", flights="fixture"))
    assert fixture["label"] == "Sample data" and fixture["travel_mode"] == "fixture"
    live = logic.source_badge(_domains(events="live", people="live", stays="live", flights="live"))
    assert live["label"] == "Live data" and live["mode"] == "live"
    no_travel = logic.source_badge(_domains(events="fixture", people="fixture"))
    assert no_travel["label"] == "Sample data" and no_travel["travel_mode"] == "unknown"


def test_core_domains_that_disagree_stay_mixed_sources() -> None:
    badge = logic.source_badge(_domains(events="live", people="fixture", stays="live", flights="live"))
    assert badge["core_mode"] == "mixed" and badge["label"] == "Mixed sources, live travel"


def test_sources_endpoint_carries_the_badge_and_the_front_uses_it() -> None:
    data = load_fixture()
    data.domains["stays"] = DomainSlice("live", "ok", T)
    data.domains["flights"] = DomainSlice("live", "ok", T)
    client = TestClient(create_app(data=data, found=Providers(), graph_probe=False))
    body = client.get("/api/v1/sources").json()
    assert body["data_source"] == "mixed"  # the envelope stays honest about the whole set
    assert body["badge"]["label"] == "Sample data, live travel"
    assert body["badge"]["core_mode"] == "fixture"
    js = client.get("/static/app.js").text
    start = js.index("function updateGlobalBadges(")
    body_js = js[start:js.find("\n  function ", start + 1)]
    assert "envelopes.sources.badge" in body_js and "apiBadge.label" in body_js
    assert "apiBadge.core_mode" in body_js  # colour follows the conference data, not "mixed"
