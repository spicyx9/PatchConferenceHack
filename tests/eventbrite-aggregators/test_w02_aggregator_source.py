"""AggregatorSource HTTP handling, run() envelope, normalization relation rules, fixtures."""

from __future__ import annotations

import json

import httpx
import pytest
from w02_helpers import COLLECTED_AT, read_fixture, static_client

from conferge.core.schemas import DiscoveryQuery, SourceRecord, SourceRef
from conferge.events.aggregators import conferenceparties as cp
from conferge.events.aggregators import source as agg_source
from conferge.events.aggregators.common import rsvp_refs
from conferge.events.aggregators.normalize import normalize_record, normalize_records
from conferge.events.aggregators.source import AggregatorSource
from conferge.events.eventbrite import normalize as eb_normalize
from conferge.events.eventbrite import source as eb_source

GH_URL = "https://conferenceparties.com/github26/"
RD_LEGACY_URL = "https://www.raidandev.org/vegas/reinvent2026/"


def _gh_client() -> httpx.AsyncClient:
    return static_client(
        {GH_URL: httpx.Response(200, text=read_fixture("conferenceparties_github26.html"))}
    )


async def test_http_403_without_brightdata_failed_blocked() -> None:
    client = static_client({GH_URL: httpx.Response(403, text="forbidden")})
    result = await AggregatorSource("conferenceparties", "github26", client=client).discover(
        DiscoveryQuery(domain="events")
    )
    report = result.run_report
    assert report.status == "failed"
    assert report.termination == "blocked"
    assert report.pages == 0
    assert result.items == []
    assert any("403" in e for e in result.errors)


async def test_http_404_failed_error() -> None:
    client = static_client({})
    result = await AggregatorSource("conferenceparties", "nope", client=client).discover(
        DiscoveryQuery(domain="events")
    )
    assert result.run_report.status == "failed"
    assert result.run_report.termination == "error"
    assert any("404" in e for e in result.errors)


async def test_http_429_rate_limited() -> None:
    client = static_client({GH_URL: httpx.Response(429)})
    result = await AggregatorSource("conferenceparties", "github26", client=client).discover(
        DiscoveryQuery(domain="events")
    )
    assert result.run_report.termination == "rate_limited"
    assert result.run_report.status == "failed"


async def test_network_error_failed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("slow", request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    result = await AggregatorSource("conferenceparties", "github26", client=client).discover(
        DiscoveryQuery(domain="events")
    )
    assert result.run_report.status == "failed"
    assert result.run_report.termination == "error"
    assert any("ConnectTimeout" in e for e in result.errors)


async def test_403_retried_through_unlocker_when_configured() -> None:
    class FakeBrightData:
        unlocker_zone = "zone"

        def __init__(self) -> None:
            self.urls: list[str] = []

        async def unlock(self, url: str) -> str:
            self.urls.append(url)
            return read_fixture("conferenceparties_github26.html")

    bd = FakeBrightData()
    client = static_client({GH_URL: httpx.Response(403)})
    result = await AggregatorSource(
        "conferenceparties", "github26", client=client, brightdata=bd  # type: ignore[arg-type]
    ).discover(DiscoveryQuery(domain="events"))
    assert bd.urls == [GH_URL]
    assert result.run_report.status == "ok"
    assert len(result.items) == 7
    assert any("Web Unlocker" in w for w in result.run_report.warnings)


async def test_limit_truncates_with_page_cap() -> None:
    result = await AggregatorSource("conferenceparties", "github26", client=_gh_client()).discover(
        DiscoveryQuery(domain="events", limit=3)
    )
    assert len(result.items) == 3
    assert result.run_report.termination == "page_cap"
    assert result.run_report.status == "degraded"
    assert result.run_report.unique_count == 3


def test_unknown_site_rejected() -> None:
    with pytest.raises(ValueError):
        AggregatorSource("nosuchsite", "x")  # type: ignore[arg-type]


async def test_fetch_details_rereads_row() -> None:
    source = AggregatorSource("conferenceparties", "github26", client=_gh_client())
    listing = await source.discover(DiscoveryQuery(domain="events"))
    target = listing.items[2]
    record = await source.fetch_details(SourceRef(provider="conferenceparties",
                                                  source_id=target.source_id))
    assert record.payload["title"] == target.payload["title"]
    with pytest.raises(LookupError):
        await source.fetch_details(SourceRef(provider="conferenceparties", source_id="missing"))


async def test_run_two_targets_one_failing_degraded() -> None:
    routes = {
        GH_URL: httpx.Response(200, text=read_fixture("conferenceparties_github26.html")),
        RD_LEGACY_URL: httpx.Response(200, text=read_fixture("raidandev_legacy_slug_home.html")),
    }

    def factory(site, slug):
        return AggregatorSource(site, slug, client=static_client(routes))

    query = DiscoveryQuery(
        domain="events", conference_id="github-universe-2026", city="San Francisco",
        filters={"aggregators": [
            {"site": "conferenceparties", "slug": "github26"},
            {"site": "raidandev", "slug": "reinvent2026"},
        ]},
    )
    envelope = await agg_source.run(query, source_factory=factory)
    assert envelope.status == "degraded"
    assert envelope.source_mode == "live"
    assert len(envelope.items) == 7
    statuses = sorted(r.status for r in envelope.reports)
    assert statuses == ["failed", "ok"]
    assert any("no event cards" in e for e in envelope.errors)
    for event in envelope.items:
        assert event.conference_id == "github-universe-2026"
        assert event.conference_relation == "candidate"
        assert event.relation_evidence
        assert event.evidence[0].source_mode == "live"
        assert event.evidence[0].collected_at is not None


async def test_run_all_ok_and_all_failed() -> None:
    ok_routes = {GH_URL: httpx.Response(200, text=read_fixture("conferenceparties_github26.html"))}
    envelope = await agg_source.run(
        DiscoveryQuery(domain="events", conference_id="github-universe-2026"),
        source_factory=lambda site, slug: AggregatorSource(site, slug,
                                                           client=static_client(ok_routes)),
    )
    assert envelope.status == "ok" and len(envelope.items) == 7  # default target github26

    envelope = await agg_source.run(
        DiscoveryQuery(domain="events", conference_id="github-universe-2026"),
        source_factory=lambda site, slug: AggregatorSource(site, slug, client=static_client({})),
    )
    assert envelope.status == "failed" and envelope.items == []


async def test_run_without_targets_failed() -> None:
    envelope = await agg_source.run(DiscoveryQuery(domain="events", conference_id="unknown"))
    assert envelope.status == "failed"
    assert envelope.errors


def _gh_records():
    return cp.parse_page(
        read_fixture("conferenceparties_github26.html"), slug="github26",
        collected_at=COLLECTED_AT, source_mode="live",
    ).records


def test_relation_candidate_only_with_conference_id() -> None:
    record = _gh_records()[0]
    with_conf = normalize_record(record, conference_id="github-universe-2026")
    assert with_conf.conference_relation == "candidate"
    assert with_conf.relation_evidence == [f"listed_on_aggregator:{GH_URL}"]
    without = normalize_record(record)
    assert without.conference_relation == "unknown"
    assert without.relation_evidence == []
    assert without.conference_id is None
    for event in (with_conf, without):
        assert event.conference_relation not in {"official", "confirmed_side_event"}
        assert event.evidence[0].source_mode == "live"
        assert event.evidence[0].collected_at == COLLECTED_AT
        assert event.evidence[0].source_record_id == record.source_id
        assert event.first_listed_at is not None and event.first_listed_at.tzinfo is not None


def test_rsvp_refs_route_platform_links_only() -> None:
    refs = rsvp_refs(_gh_records())
    assert [(r.provider, r.source_id) for r in refs] == [
        ("luma", "https://luma.com/git-together"),
    ]


def test_load_fixture_records_requires_opt_in() -> None:
    with pytest.raises(RuntimeError):
        agg_source.load_fixture_records()
    with pytest.raises(RuntimeError):
        eb_source.load_fixture_records()


def test_fixture_file_records_are_labelled_and_normalize() -> None:
    if not agg_source.FIXTURE_PATH.exists():
        pytest.skip("fixtures/eventbrite-aggregators.json not present yet")
    data = json.loads(agg_source.FIXTURE_PATH.read_text(encoding="utf-8"))
    assert data.get("source_mode") == "fixture"
    agg = agg_source.load_fixture_records(explicit_opt_in=True)
    ebr = eb_source.load_fixture_records(explicit_opt_in=True)
    assert agg or ebr
    for record in agg + ebr:
        assert isinstance(record, SourceRecord)
        assert record.source_mode == "fixture"
        assert record.collected_at.tzinfo is not None
        assert record.source_url is not None
    agg_events, agg_errors = normalize_records(agg, conference_id="github-universe-2026")
    assert agg_errors == [] and len(agg_events) == len(agg)
    eb_events, eb_errors = eb_normalize.normalize_records(ebr)
    assert eb_errors == [] and len(eb_events) == len(ebr)
    for event in agg_events + eb_events:
        assert event.evidence and event.evidence[0].source_mode == "fixture"


def test_fixture_loader_rejects_unlabelled_records(tmp_path, monkeypatch) -> None:
    record = _gh_records()[0].model_dump(mode="json")  # source_mode live
    path = tmp_path / "fx.json"
    path.write_text(json.dumps({"aggregators": [record], "eventbrite": [record]}))
    monkeypatch.setattr(agg_source, "FIXTURE_PATH", path)
    monkeypatch.setattr(eb_source, "FIXTURE_PATH", path)
    with pytest.raises(ValueError):
        agg_source.load_fixture_records(explicit_opt_in=True)
    with pytest.raises(ValueError):
        eb_source.load_fixture_records(explicit_opt_in=True)
