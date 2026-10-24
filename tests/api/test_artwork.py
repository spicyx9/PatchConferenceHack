"""Artwork keeps exact identity, public access and fixture provenance."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from conferge.api import artwork
from conferge.api.app import create_app
from conferge.api.data import load_fixture
from conferge.api.providers import Providers
from conferge.core.schemas import Event, SourceEvidence

COVER = "https://images.lumacdn.com/uploads/example.png"


def write_fixture(path: Path, **event_fields: object) -> Path:
    path.write_text(json.dumps({
        "source_mode": "fixture",
        "entries": [{"api_id": "wrong-outer-id", "event": {
            "api_id": "evt-public", "visibility": "public", "cover_url": COVER,
            **event_fields,
        }}],
    }), encoding="utf-8")
    return path


def fixture_event(**fields: object) -> Event:
    return Event.model_validate({
        "id": "luma:evt-public", "title": "Public event", "event_type": "meetup",
        "evidence": [{"provider": "luma", "source_mode": "fixture"}], **fields,
    })


def test_public_fixture_artwork_requires_exact_nested_id(tmp_path: Path) -> None:
    covers = artwork.load_fixture_covers(write_fixture(tmp_path / "luma.json"))
    assert covers == {"luma:evt-public": COVER}
    art = artwork.event_artwork(fixture_event(), covers)
    assert {k: art[k] for k in ("cover_url", "cover_source_mode")} == {
        "cover_url": COVER, "cover_source_mode": "fixture",
    }
    assert set(art) <= {"cover_url", "cover_source_mode", "cover_captured_at"}
    assert artwork.event_artwork(fixture_event(id="luma:wrong-outer-id"), covers) == {}


@pytest.mark.parametrize("url", [
    "http://images.lumacdn.com/x.png", "https://other.example/x.png",
    "https://images.lumacdn.com.evil.example/x.png",
    "https://user@images.lumacdn.com/x.png", "https://images.lumacdn.com:443/x.png",
    "javascript:alert(1)", "//images.lumacdn.com/x.png",
    "https://images.lumacdn.com/\nx.png", "https://images.lumacdn.com", None, 123,
])
def test_unsafe_or_missing_cover_is_omitted(tmp_path: Path, url: object) -> None:
    assert artwork.load_fixture_covers(write_fixture(tmp_path / "luma.json", cover_url=url)) == {}


@pytest.mark.parametrize("visibility", ["private", "unlisted", None])
def test_nonpublic_artwork_is_omitted(tmp_path: Path, visibility: object) -> None:
    assert artwork.load_fixture_covers(
        write_fixture(tmp_path / "luma.json", visibility=visibility),
    ) == {}


@pytest.mark.parametrize("raw", ["{", "[]", "null", '{"source_mode":"live","entries":[]}',
                                  '{"source_mode":"fixture","entries":{}}',
                                  '{"source_mode":"fixture","entries":[null,{"event":[]}]}'])
def test_malformed_fixture_is_optional(tmp_path: Path, raw: str) -> None:
    path = tmp_path / "luma.json"
    path.write_text(raw, encoding="utf-8")
    assert artwork.load_fixture_covers(path) == {}


def test_missing_fixture_is_optional(tmp_path: Path) -> None:
    assert artwork.load_fixture_covers(tmp_path / "missing.json") == {}


@pytest.mark.parametrize("fields", [
    {"evidence": []},
    {"evidence": [{"provider": "luma", "source_mode": "live"}]},
    {"evidence": [{"provider": "luma", "source_mode": "cached"}]},
    {"evidence": [{"provider": "luma", "source_mode": "fixture"},
                  {"provider": "other", "source_mode": "live"}]},
    {"evidence": [{"provider": "official", "source_mode": "fixture"}]},
    {"event_type": "session"},
    {"conference_relation": "official", "relation_evidence": ["official program"]},
])
def test_other_modes_and_official_sessions_have_no_fixture_cover(fields: dict) -> None:
    assert artwork.event_artwork(fixture_event(**fields), {"luma:evt-public": COVER}) == {}


def test_events_api_exposes_only_matching_fixture_cover(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(artwork, "FIXTURE_PATH", write_fixture(tmp_path / "luma.json"))
    data = load_fixture()
    data.events = [fixture_event(), fixture_event(id="luma:another"), fixture_event(
        id="live-copy", evidence=[SourceEvidence(provider="luma", source_mode="live")],
    )]
    with TestClient(create_app(data=data, found=Providers(), graph_probe=False)) as client:
        response = client.get("/api/v1/events")
    assert response.status_code == 200
    items = {e["id"]: e for e in response.json()["items"]}
    assert items["luma:evt-public"]["cover_url"] == COVER
    assert items["luma:evt-public"]["cover_source_mode"] == "fixture"
    assert "cover_url" not in items["luma:another"]
    assert "cover_url" not in items["live-copy"]
