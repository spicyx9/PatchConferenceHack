"""Offline tests for the Sessionize adapter. All data below is fictional (Example Conf)."""

from __future__ import annotations

import copy
from datetime import datetime, timezone

import httpx
import pytest

from conferge.core.schemas import DiscoveryQuery, SourceRef
from conferge.events.official.sessionize import (
    SessionizeSource,
    find_endpoint_ids,
    normalize_view_all,
    view_all_url,
)

ENDPOINT = "abc123xy"
URL = view_all_url(ENDPOINT)
COLLECTED = datetime(2026, 10, 23, 12, 0, tzinfo=timezone.utc)

SAMPLE = {
    "sessions": [
        {
            "id": "1001", "title": "Agents in Example Conf", "description": "A fictional talk.",
            "startsAt": "2026-10-28T09:00:00", "endsAt": "2026-10-28T09:45:00",
            "isServiceSession": False, "isPlenumSession": False,
            "speakers": ["spk-a"], "categoryItems": [11], "roomId": 7, "status": "Accepted",
        },
        {
            "id": "1002", "title": "Hands-on Fictional Lab", "description": None,
            "startsAt": "2026-10-28T13:00:00", "endsAt": "2026-10-28T15:00:00",
            "isServiceSession": False, "isPlenumSession": False,
            "speakers": [], "categoryItems": [12], "roomId": 8, "status": "Accepted",
        },
    ],
    "speakers": [
        {
            "id": "spk-a", "firstName": "Ada", "lastName": "Example", "fullName": "Ada Example",
            "bio": "Fictional speaker.", "tagLine": "Founder, Example Labs",
            "profilePicture": None, "sessions": [1001], "isTopSpeaker": True,
            "links": [
                {"title": "X (Twitter)", "url": "https://twitter.com/ada_example",
                 "linkType": "Twitter"},
                {"title": "LinkedIn", "url": "https://www.linkedin.com/in/ada-example",
                 "linkType": "LinkedIn"},
                {"title": "Blog", "url": "not a url", "linkType": "Blog"},
            ],
        },
        {
            "id": "spk-b", "firstName": "Bo", "lastName": "Sample", "fullName": "Bo Sample",
            "bio": None, "tagLine": None, "profilePicture": None, "sessions": [],
            "isTopSpeaker": False, "links": [],
        },
        {"id": "spk-c", "firstName": "", "lastName": "", "fullName": "", "sessions": [],
         "links": []},
    ],
    "rooms": [{"id": 7, "name": "Hall A"}, {"id": 8, "name": "Lab Room"}],
    "categories": [
        {"id": 1, "title": "Format", "items": [
            {"id": 11, "name": "Talk"}, {"id": 12, "name": "Workshop"}]},
    ],
    "questions": [],
}


def _norm(tz: str | None = "America/Los_Angeles", conference_id: str | None = "example-conf"):
    return normalize_view_all(
        copy.deepcopy(SAMPLE), conference_id=conference_id, timezone=tz, source_url=URL,
        collected_at=COLLECTED, source_mode="live", endpoint_id=ENDPOINT,
    )


def _source(handler) -> tuple[SessionizeSource, httpx.AsyncClient]:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return SessionizeSource(ENDPOINT, conference_id="example-conf",
                            timezone="America/Los_Angeles", client=client), client


def test_find_endpoint_ids_dedupes_and_preserves_order():
    html = (
        '<script src="https://sessionize.com/api/v2/zz9abc/view/GridSmart"></script>'
        '<a href="https://SESSIONIZE.com/api/v2/ab12cd/view/All">x</a>'
        '<div data-x="sessionize.com/api/v2/zz9abc/view/Speakers"></div>'
    )
    assert find_endpoint_ids(html) == ["zz9abc", "ab12cd"]
    assert find_endpoint_ids("") == []


def test_happy_path_normalization_with_timezone():
    parse = _norm()
    events = {e.id: e for e in parse.events}
    talk = events["sessionize:example-conf:session:1001"]
    assert talk.start_at == datetime(2026, 10, 28, 16, 0, tzinfo=timezone.utc)
    assert talk.end_at.astimezone(timezone.utc) == datetime(2026, 10, 28, 16, 45,
                                                            tzinfo=timezone.utc)
    assert talk.timezone == "America/Los_Angeles"
    assert talk.room == "Hall A" and talk.topics == ["Talk"]
    assert talk.event_type == "session" and talk.status == "scheduled"
    assert talk.conference_relation == "official" and talk.relation_evidence
    assert ENDPOINT in talk.relation_evidence[0]
    assert talk.speaker_ids == ["person:sessionize:spk-a"]
    assert talk.evidence[0].source_record_id == "1001"
    assert talk.evidence[0].collected_at == COLLECTED

    lab = events["sessionize:example-conf:session:1002"]
    assert lab.event_type == "workshop" and lab.description is None

    people = {p.id: p for p in parse.people}
    ada = people["person:sessionize:spk-a"]
    assert ada.name == "Ada Example" and ada.title == "Founder, Example Labs"
    assert ada.participation == "confirmed_speaker"
    assert ada.event_ids == ["sessionize:example-conf:session:1001"]
    assert ada.x_handle == "ada_example"
    assert str(ada.linkedin_url) == "https://www.linkedin.com/in/ada-example"
    assert "person:sessionize:spk-c" not in people
    assert any("spk-c" in w for w in parse.warnings)


def test_missing_timezone_leaves_times_unset():
    parse = _norm(tz=None)
    for event in parse.events:
        assert event.start_at is None and event.end_at is None
        assert event.timezone is None and event.status == "unknown"


def test_malformed_timezone_leaves_times_unset_with_warning():
    parse = _norm(tz="Not/A_Zone")
    assert all(e.start_at is None and e.timezone is None for e in parse.events)
    assert any("invalid timezone" in w for w in parse.warnings)


def test_offset_in_source_is_honored_without_timezone():
    data = copy.deepcopy(SAMPLE)
    data["sessions"][0]["startsAt"] = "2026-10-28T09:00:00-07:00"
    data["sessions"][0]["endsAt"] = None
    parse = normalize_view_all(data, conference_id=None, timezone=None, source_url=URL,
                               collected_at=COLLECTED, source_mode="live")
    talk = next(e for e in parse.events if e.id.endswith(":1001"))
    assert talk.start_at == datetime(2026, 10, 28, 16, 0, tzinfo=timezone.utc)
    assert talk.conference_relation == "unknown" and talk.relation_evidence == []
    assert talk.id == "sessionize:sessionize:session:1001"


def test_speaker_without_sessions_is_unknown_participation():
    bo = next(p for p in _norm().people if p.id == "person:sessionize:spk-b")
    assert bo.participation == "unknown" and bo.event_ids == []


def test_session_without_speakers_has_empty_speaker_ids():
    lab = next(e for e in _norm().events if e.id.endswith(":1002"))
    assert lab.speaker_ids == []


def test_invalid_link_url_becomes_none():
    ada = next(p for p in _norm().people if p.id == "person:sessionize:spk-a")
    assert ada.public_profile_url is None


async def test_discover_happy_path_records():
    calls: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(req)
        return httpx.Response(200, json=SAMPLE)

    source, client = _source(handler)
    async with client:
        res = await source.discover(DiscoveryQuery(domain="conference"))
    assert str(calls[0].url) == URL
    assert res.run_report.status == "ok"
    assert res.run_report.termination == "not_applicable"
    ids = [r.source_id for r in res.items]
    assert "session:1001" in ids and "speaker:spk-a" in ids
    rec = res.items[0]
    assert rec.source_mode == "live" and rec.collected_at.tzinfo is not None
    assert rec.content_hash and len(rec.content_hash) == 64
    assert str(rec.source_url) == URL


async def test_discover_404_is_failed_without_exception():
    source, client = _source(lambda req: httpx.Response(404, text="nope"))
    async with client:
        res = await source.discover(DiscoveryQuery(domain="conference"))
    assert res.run_report.status == "failed" and res.run_report.termination == "error"
    assert res.items == [] and res.run_report.errors and "404" in res.errors[0]


@pytest.mark.parametrize("code,term", [(429, "rate_limited"), (403, "blocked")])
async def test_discover_rate_limit_and_block(code, term):
    source, client = _source(lambda req: httpx.Response(code))
    async with client:
        res = await source.discover(DiscoveryQuery(domain="conference"))
    assert res.run_report.status == "failed" and res.run_report.termination == term


async def test_discover_network_error_is_failed():
    def handler(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=req)

    source, client = _source(handler)
    async with client:
        res = await source.discover(DiscoveryQuery(domain="conference"))
    assert res.run_report.status == "failed" and res.items == []


async def test_discover_non_json_is_schema_changed():
    source, client = _source(lambda req: httpx.Response(200, text="<html>hi</html>"))
    async with client:
        res = await source.discover(DiscoveryQuery(domain="conference"))
    assert res.run_report.status == "failed"
    assert res.run_report.termination == "schema_changed"


async def test_discover_zero_sessions_is_failed():
    empty = {"sessions": [], "speakers": [], "rooms": [], "categories": [], "questions": []}
    source, client = _source(lambda req: httpx.Response(200, json=empty))
    async with client:
        res = await source.discover(DiscoveryQuery(domain="conference"))
    assert res.run_report.status == "failed" and res.run_report.termination == "error"
    assert "zero sessions" in res.errors[0]


async def test_fetch_details_found_and_missing():
    source, client = _source(lambda req: httpx.Response(200, json=SAMPLE))
    async with client:
        rec = await source.fetch_details(SourceRef(provider="sessionize",
                                                   source_id="speaker:spk-b"))
        assert rec.payload["fullName"] == "Bo Sample"
        with pytest.raises(LookupError):
            await source.fetch_details(SourceRef(provider="sessionize",
                                                 source_id="session:9999"))
