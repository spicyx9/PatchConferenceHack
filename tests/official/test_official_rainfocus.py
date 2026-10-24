"""Offline tests for the GitHub Universe RainFocus adapter (MockTransport, no network)."""

from __future__ import annotations

import copy
from datetime import datetime, timezone
from typing import Any

import httpx
import pytest

from conferge.core.contracts import Source
from conferge.core.schemas import DiscoveryQuery, SourceRef
from conferge.events.official.normalize import (
    infer_roles,
    normalize_catalog,
    normalize_exhibitor,
    normalize_session,
    split_room,
)
from conferge.events.official.rainfocus import RainFocusClient, extract_widget_id
from conferge.events.official.source import OfficialConferenceSource

NOW = datetime(2026, 10, 24, 6, 0, tzinfo=timezone.utc)

# Fictional records shaped like the public RainFocus catalog payload.
SESSION: dict[str, Any] = {
    "sessionID": "S1", "code": "TST100", "title": "Example agents talk",
    "abstract": "<p>Agents &amp; MCP in practice.</p>", "type": "Breakout Session",
    "status": "Accepted", "published": 1.0,
    "times": [{
        "sessionTimeID": "T1", "date": "2026-10-28", "startTime": "10:00", "endTime": "10:30",
        "utcStartTime": "2026/10/28 17:00:00", "utcEndTime": "2026/10/28 17:30:00",
        "room": "Cowell Theater @ Gateway Pavilion", "capacity": "300",
    }],
    "participants": [{
        "speakerId": "P1", "fullName": "Example Speaker", "companyName": "Example Corp",
        "jobTitle": "Senior Product Manager", "roles": "Speaker",
        "linkedIn": "https://www.linkedin.com/in/example-speaker/", "twitter": "@example_sp",
        "bio": "<p>Builds things.</p>",
        "session": [{"sessionID": "REHEARSAL", "published": "false"}],
    }],
    "attributevalues": [
        {"attribute_id": "Topic", "value": "AI: Agents"},
        {"attribute_id": "Track", "value": "Build software, not code"},
        {"attribute_id": "SessionTrackNotMulti", "value": "Build software, not code"},
        {"attribute_id": "GitHubproduct", "value": "GitHub Copilot"},
    ],
}
SOCIAL: dict[str, Any] = {
    "sessionID": "S2", "code": "2000", "title": "Example Developer Meetup", "type": "Social",
    "status": "Accepted", "published": 1.0, "participants": [],
    "times": [{"sessionTimeID": "T2", "date": "2026-10-28", "startTime": "18:00",
               "endTime": "20:00", "utcStartTime": "2026/10/29 01:00:00",
               "utcEndTime": "2026/10/29 03:00:00", "room": "Example HQ @ 1 Example St"}],
    "attributevalues": [],
}
EXHIBITOR: dict[str, Any] = {
    "exhibitorID": "X1", "name": "Example Corp", "published": 1.0,
    "externalLink": "https://www.example.com", "linkedinLink": "",
    "booths": [{"booth": "101"}],
    "attributevalues": [{"attribute_id": "ExhibitorType", "value": "Gold"},
                        {"attribute_id": "Industry", "value": "Software"}],
}


def _norm(item: dict[str, Any], **kw: Any):
    return normalize_session(item, collected_at=NOW, source_mode="fixture", **kw)


def test_session_normalization_times_room_speaker():
    events, people, companies, warnings = _norm(SESSION)
    assert len(events) == 1 and warnings == []
    event = events[0]
    assert event.conference_relation == "official" and event.relation_evidence
    assert event.start_at.isoformat() == "2026-10-28T10:00:00-07:00"
    assert event.start_at.astimezone(timezone.utc).hour == 17
    assert event.timezone == "America/Los_Angeles"
    assert event.room == "Cowell Theater @ Gateway Pavilion"
    assert event.venue.name == "Gateway Pavilion" and event.venue.address is None
    assert event.description == "Agents & MCP in practice."
    assert event.capacity == 300 and event.status == "scheduled"
    assert "AI: Agents" in event.topics and "GitHub Copilot" in event.topics
    assert event.price_min is None and event.is_free is None
    assert event.evidence[0].source_mode == "fixture"
    person = people[0]
    assert person.participation == "confirmed_speaker"
    assert person.event_ids == [event.id]  # unpublished rehearsal is not linked
    assert person.company_id == "company:example-corp" and companies[0].name == "Example Corp"
    assert person.x_handle == "example_sp" and person.roles == ["pm"]
    assert person.bio == "Builds things."


def test_missing_speaker_creates_no_person():
    item = copy.deepcopy(SESSION)
    item["participants"] = []
    events, people, _, warnings = _norm(item)
    assert events[0].speaker_ids == [] and people == []
    assert any("no published speakers" in w for w in warnings)


def test_participant_without_name_is_skipped_not_invented():
    item = copy.deepcopy(SESSION)
    item["participants"] = [{"speakerId": "P9", "roles": "Speaker"}]
    events, people, _, warnings = _norm(item)
    assert people == [] and events[0].speaker_ids == []
    assert any("without id or name" in w for w in warnings)


def test_ambiguous_track_keeps_all_and_warns():
    item = copy.deepcopy(SESSION)
    item["attributevalues"] = [
        {"attribute_id": "Track", "value": "Build software, not code"},
        {"attribute_id": "Track", "value": "Trust every commit"},
    ]
    events, _, _, warnings = _norm(item)
    assert {"Build software, not code", "Trust every commit"} <= set(events[0].topics)
    assert any("ambiguous track" in w for w in warnings)


def test_malformed_timezone_keeps_utc_instant_and_nulls_timezone():
    events, _, _, warnings = _norm(SESSION, timezone_name="Mars/Olympus_Mons")
    event = events[0]
    assert event.timezone is None
    assert event.start_at == datetime(2026, 10, 28, 17, 0, tzinfo=timezone.utc)
    assert any("malformed timezone" in w for w in warnings)


def test_malformed_utc_without_timezone_gives_no_time():
    item = copy.deepcopy(SESSION)
    item["times"][0]["utcStartTime"] = "soon"
    item["times"][0]["utcEndTime"] = None
    events, _, _, warnings = _norm(item, timezone_name=None)
    assert events[0].start_at is None and events[0].end_at is None
    assert events[0].status == "unknown"
    assert any("unparseable utcStartTime" in w for w in warnings)


def test_no_times_means_no_start():
    item = copy.deepcopy(SESSION)
    item["times"] = []
    events, _, _, warnings = _norm(item)
    assert events[0].start_at is None and events[0].status == "unknown"
    assert any("no published time" in w for w in warnings)


def test_unpublished_session_skipped():
    item = copy.deepcopy(SESSION)
    item["published"] = 0.0
    assert _norm(item)[0] == []


def test_multi_slot_session_gets_one_event_per_slot():
    item = copy.deepcopy(SESSION)
    second = dict(item["times"][0], sessionTimeID="T9", utcStartTime="2026/10/29 17:00:00",
                  utcEndTime="2026/10/29 17:30:00", date="2026-10-29")
    item["times"].append(second)
    events, people, _, _ = _norm(item)
    assert len({e.id for e in events}) == 2
    assert set(people[0].event_ids) == {e.id for e in events}


def test_social_is_confirmed_side_event_not_official():
    events, people, _, warnings = _norm(SOCIAL)
    event = events[0]
    assert event.conference_relation == "confirmed_side_event"
    assert event.event_type == "meetup" and event.organizer_names == []
    assert event.venue.name == "Example HQ" and event.venue.address == "1 Example St"
    assert event.start_at.isoformat() == "2026-10-28T18:00:00-07:00"
    assert people == [] and warnings == []


def test_exhibitor_becomes_sponsor_company_and_merges_with_speaker_company():
    company, warnings = normalize_exhibitor(EXHIBITOR, collected_at=NOW, source_mode="fixture")
    assert warnings == [] and company.domain == "example.com"
    assert company.categories == ["sponsor", "sponsor_tier:gold", "booth:101"]
    assert company.linkedin_url is None and company.industry == "Software"
    catalog = normalize_catalog([SESSION, SOCIAL], [EXHIBITOR], collected_at=NOW,
                                source_mode="fixture")
    assert [c.id for c in catalog.companies] == ["company:example-corp"]
    assert catalog.conference.sponsor_ids == ["company:example-corp"]
    assert catalog.conference.start_date.isoformat() == "2026-10-28"
    assert len(catalog.events) == 2 and len(catalog.people) == 1


def test_split_room_and_roles():
    assert split_room(None, side_event=False) is None
    venue = split_room("Tonga Room @ Fairmont Hotel, 950 Mason St", side_event=True)
    assert venue.name == "Tonga Room" and venue.address == "Fairmont Hotel, 950 Mason St"
    assert infer_roles("Director, Product Management") == ["pm"]
    assert infer_roles("Director") == []
    assert infer_roles("Developer Advocate") == ["devrel"]


def test_extract_widget_id():
    page = {"children": '<div class="rf-widget" id="rf-catalog" data-widgetid="W123abc" />'}
    assert extract_widget_id(page, "session") == "W123abc"
    assert extract_widget_id(page, "exhibitor") is None


# ---------- HTTP layer ----------

def _page_payload(kind: str) -> dict[str, Any]:
    element = "rf-catalog" if kind == "sessioncatalog" else "rf-exhibitorcatalog"
    return {"data": {
        "responseCode": "0",
        "pageData": {"children": f'<div id="{element}" data-widgetid="W{kind}" />'},
        "widgetConf": {"apiProfileToken": "public-token-not-logged"},
    }}


def _transport(sessions: list[dict], exhibitors: list[dict], *, page_size: int = 1,
               fail: dict[str, int] | None = None, stuck: bool = False):
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.path.endswith("/flow/loadPage"):
            return httpx.Response(200, json=_page_payload(request.url.params["pageUri"]))
        form = dict(x.split("=", 1) for x in request.content.decode().split("&"))
        kind = form["type"]
        if fail and kind in fail:
            return httpx.Response(fail[kind], text="nope")
        assert request.headers["rfApiProfileId"] == "public-token-not-logged"
        rows = sessions if kind == "session" else exhibitors
        offset = 0 if stuck else int(form["from"])
        chunk = rows[offset: offset + page_size]
        if offset == 0:
            return httpx.Response(200, json={
                "responseCode": "0", "totalSearchItems": len(rows),
                "sectionList": [{"total": len(rows), "items": chunk}],
            })
        return httpx.Response(200, json={"responseCode": "0", "total": len(rows),
                                         "items": chunk})

    return httpx.MockTransport(handler), calls


def _source(transport: httpx.MockTransport) -> OfficialConferenceSource:
    http = httpx.AsyncClient(transport=transport)
    return OfficialConferenceSource(RainFocusClient(http, delay_s=0))


SECOND = dict(copy.deepcopy(SESSION), sessionID="S3", code="TST101")


async def test_discover_paginates_to_exhaustion():
    transport, calls = _transport([SESSION, SOCIAL, SECOND], [EXHIBITOR])
    source = _source(transport)
    assert isinstance(source, Source)
    result = await source.discover(DiscoveryQuery(domain="conference", limit=1000))
    report = result.run_report
    assert report.status == "ok" and report.termination == "exhausted"
    assert report.unique_count == 4 and report.expected_count == 4 and report.pages == 4
    assert {r.source_id for r in result.items} >= {"session:S1", "exhibitor:X1"}
    assert all(r.source_mode == "live" and r.content_hash for r in result.items)
    assert "public-token-not-logged" not in str(report.model_dump())


async def test_collect_normalizes_with_live_mode():
    transport, _ = _transport([SESSION, SOCIAL], [EXHIBITOR], page_size=50)
    collection = await _source(transport).collect()
    assert collection.status == "ok" and collection.source_mode == "live"
    assert len(collection.events.items) == 2 and collection.conference is not None
    assert all(e.evidence[0].source_mode == "live" for e in collection.events.items)


async def test_exhibitor_failure_degrades_without_fixture():
    transport, _ = _transport([SESSION], [EXHIBITOR], fail={"exhibitor": 429})
    result = await _source(transport).discover(DiscoveryQuery(domain="conference"))
    assert result.run_report.status == "degraded"
    assert result.run_report.termination == "rate_limited"
    assert all(r.source_mode == "live" for r in result.items)
    assert any("HTTP 429" in e for e in result.errors)


async def test_total_failure_reports_failed():
    transport, _ = _transport([SESSION], [EXHIBITOR], fail={"session": 403, "exhibitor": 500})
    collection = await _source(transport).collect()
    assert collection.status == "failed" and collection.events.items == []
    assert collection.conference is None
    assert collection.events.reports[0].termination == "blocked"


async def test_repeated_page_is_cursor_stuck():
    transport, _ = _transport([SESSION, SECOND], [EXHIBITOR], stuck=True)
    result = await _source(transport).discover(DiscoveryQuery(domain="conference"))
    assert result.run_report.status == "degraded"
    assert result.run_report.termination == "cursor_stuck"


async def test_query_limit_is_reported_as_page_cap():
    transport, _ = _transport([SESSION, SECOND, SOCIAL], [EXHIBITOR], page_size=50)
    result = await _source(transport).discover(DiscoveryQuery(domain="conference", limit=1))
    assert result.run_report.status == "degraded"
    assert result.run_report.termination == "page_cap"


async def test_schema_change_on_non_json():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>shell</html>")

    result = await _source(httpx.MockTransport(handler)).discover(
        DiscoveryQuery(domain="conference"))
    assert result.run_report.status == "failed"
    assert result.run_report.termination == "schema_changed"


async def test_other_conference_or_domain_not_applicable():
    transport, calls = _transport([SESSION], [EXHIBITOR])
    source = _source(transport)
    other = await source.discover(DiscoveryQuery(domain="events", conference_id="kubecon"))
    flights = await source.discover(DiscoveryQuery(domain="flights"))
    assert other.run_report.termination == "not_applicable" and other.items == []
    assert flights.run_report.termination == "not_applicable" and calls == []


async def test_fetch_details_found_and_missing():
    transport, _ = _transport([SESSION, SOCIAL], [EXHIBITOR], page_size=50)
    source = _source(transport)
    record = await source.fetch_details(SourceRef(provider="rainfocus", source_id="session:S2"))
    assert record.payload["title"] == "Example Developer Meetup"
    with pytest.raises(LookupError):
        await source.fetch_details(SourceRef(provider="rainfocus", source_id="session:NOPE"))
    with pytest.raises(ValueError):
        await source.fetch_details(SourceRef(provider="rainfocus", source_id="bogus"))
