"""Offline tests for SERP parsing, SerpDiscoverySource, fixture and pipeline (window 04)."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import httpx
import pytest

from conferge.core.brightdata import BrightDataClient, BrightDataError
from conferge.core.contracts import Source
from conferge.core.schemas import (
    Conference,
    DiscoveryQuery,
    Event,
    SourceRecord,
    SourceRef,
)
from conferge.events.discovery import (
    DiscoveryError,
    QueryPlan,
    SerpDiscoverySource,
    fixture_plan,
    fixture_source,
    load_fixture,
    parse_serp,
    run,
)
from conferge.events.discovery.jsonld import extract_event_jsonld
from conferge.events.discovery.pipeline import normalize_detail
from conferge.events.discovery.serp import SerpBlocked

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "discovery.json"

CONF = Conference(
    id="github-universe-2026", name="GitHub Universe", start_date=date(2026, 10, 28),
    end_date=date(2026, 10, 29), city="San Francisco", venue_name="Fort Mason Center",
    timezone="America/Los_Angeles", latitude=37.8060, longitude=-122.4320,
    topics=["AI agents", "developer tools"],
)

GOOGLE_HTML = """
<html><body>
<div><a href="/url?q=https://lu.ma/fictional-mixer&amp;sa=U"><h3>Fictional Mixer</h3></a></div>
<div><a href="https://example.org/party"><span>x</span><h3>Example <b>Party</b></h3></a></div>
<div><a href="https://www.google.com/search?q=more">More results</a></div>
</body></html>
"""

JSONLD_PAGE = """<html><head><script type="application/ld+json">
{"@context":"https://schema.org","@graph":[{"@type":"Organization","name":"X"},
{"@type":"SocialEvent","name":"Fictional Rooftop Happy Hour",
 "startDate":"2026-10-28T17:00:00-07:00","endDate":"2026-10-28T20:00:00-07:00",
 "eventStatus":"https://schema.org/EventScheduled",
 "location":{"@type":"Place","name":"Fictional Roof","address":{"streetAddress":"1 Test St",
   "addressLocality":"San Francisco"},"geo":{"latitude":37.80,"longitude":-122.43}},
 "organizer":[{"name":"Fictional Labs"}],
 "offers":{"price":"0","priceCurrency":"USD","url":"https://example.org/rsvp"},
 "description":"A GitHub Universe week happy hour."}]}
</script></head><body></body></html>"""


def _serp_from(mapping: dict[str, str], default: str = '{"organic": []}'):
    async def serp(text: str) -> str:
        value = mapping.get(text, default)
        if isinstance(value, Exception):
            raise value
        return value
    return serp


def _organic(*urls: str) -> str:
    return json.dumps({"organic": [
        {"link": u, "title": f"Title {i}", "description": None, "rank": i}
        for i, u in enumerate(urls, 1)
    ]})


# ------------------------------------------------------------------ parsing
def test_parse_serp_json():
    hits = parse_serp(_organic("https://lu.ma/a", "https://example.org/b"))
    assert [h["url"] for h in hits] == ["https://lu.ma/a", "https://example.org/b"]
    assert [h["position"] for h in hits] == [1, 2]
    assert hits[0]["snippet"] is None


def test_parse_serp_html_unwraps_and_keeps_only_h3_anchors():
    hits = parse_serp(GOOGLE_HTML)
    assert [h["url"] for h in hits] == [
        "/url?q=https://lu.ma/fictional-mixer&sa=U", "https://example.org/party",
    ]
    assert hits[1]["title"] == "Example Party"


def test_parse_serp_detects_captcha():
    with pytest.raises(SerpBlocked):
        parse_serp("<html>Our systems have detected unusual traffic</html>")


def test_parse_serp_garbage_gives_zero_hits():
    assert parse_serp("{not json") == []


# ------------------------------------------------------------------ discover
def _plan() -> QueryPlan:
    return QueryPlan(city="San Francisco", conference_name="GitHub Universe",
                     start_date=date(2026, 10, 28), end_date=date(2026, 10, 29),
                     sponsors=["Amplitude"], max_platform_days=1)


async def test_discover_without_key_fails_visibly_without_network():
    bd = BrightDataClient(api_key=None, serp_zone="zone")
    src = SerpDiscoverySource(bd)
    assert isinstance(src, Source)
    result = await src.discover(DiscoveryQuery(domain="events", city="San Francisco"))
    assert result.items == []
    assert result.run_report.status == "failed"
    assert result.run_report.source_mode == "live"
    assert "key missing" in result.errors[0]


async def test_discover_requires_city():
    src = SerpDiscoverySource(serp=_serp_from({}))
    result = await src.discover(DiscoveryQuery(domain="events"))
    assert result.run_report.status == "failed"


async def test_discover_dedups_urls_and_keeps_provenance():
    plan = _plan()
    texts = [q.text for q in __import__(
        "conferge.events.discovery.queries", fromlist=["build_queries"]).build_queries(plan)]
    mapping = {
        texts[0]: _organic("https://lu.ma/fictional-mixer", "https://www.google.com/search?q=x"),
        texts[1]: _organic("https://luma.com/fictional-mixer/?utm_source=g",
                           "https://example.org/party"),
    }
    src = SerpDiscoverySource(serp=_serp_from(mapping))
    result = await src.discover_plan(plan)
    report = result.run_report
    assert report.status == "ok" and report.termination == "not_applicable"
    urls = [r.payload["canonical_url"] for r in result.items]
    assert urls.count("https://luma.com/fictional-mixer") == 1
    luma = next(r for r in result.items if r.payload["canonical_url"].startswith("https://luma"))
    assert luma.payload["record_kind"] == "discovery_candidate"
    assert luma.payload["verified_event"] is False
    assert {h["query"] for h in luma.payload["discovered_by"]} == {texts[0], texts[1]}
    assert luma.payload["route"]["adapter"] == "luma"
    assert 0 < luma.payload["confidence"] <= 0.8
    assert luma.source_mode == "live" and luma.collected_at.tzinfo is not None
    assert report.unique_count == len(result.items) == 2
    assert any("search-engine" in w for w in report.warnings)


async def test_partial_serp_failure_is_degraded_not_fixture():
    plan = _plan()
    from conferge.events.discovery.queries import build_queries

    texts = [q.text for q in build_queries(plan)]
    mapping: dict = {texts[0]: _organic("https://example.org/a"),
                     texts[1]: BrightDataError("Bright Data /request: HTTP 502")}
    result = await SerpDiscoverySource(serp=_serp_from(mapping)).discover_plan(plan)
    assert result.run_report.status == "degraded"
    assert result.run_report.termination == "error"
    assert all(r.source_mode == "live" for r in result.items)
    assert any("HTTP 502" in e for e in result.errors)


async def test_all_blocked_is_failed_blocked():
    src = SerpDiscoverySource(serp=_serp_from({}, default="<html>unusual traffic</html>"))
    result = await src.discover_plan(_plan())
    assert result.run_report.status == "failed"
    assert result.run_report.termination == "blocked"


async def test_zero_results_is_degraded():
    result = await SerpDiscoverySource(serp=_serp_from({})).discover_plan(_plan())
    assert result.run_report.status == "degraded"
    assert result.items == []


async def test_limit_truncation_is_page_cap():
    from conferge.events.discovery.queries import build_queries

    plan = _plan()
    first = build_queries(plan)[0].text
    mapping = {first: _organic(*[f"https://example.org/{i}" for i in range(5)])}
    result = await SerpDiscoverySource(serp=_serp_from(mapping)).discover_plan(plan, limit=2)
    assert len(result.items) == 2
    assert result.run_report.termination == "page_cap"
    assert result.run_report.status == "degraded"


async def test_bounded_concurrency():
    import asyncio

    active = 0
    peak = 0

    async def serp(_: str) -> str:
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.001)
        active -= 1
        return '{"organic": []}'

    await SerpDiscoverySource(serp=serp, concurrency=2).discover_plan(_plan())
    assert peak <= 2


async def test_serp_uses_shared_brightdata_client():
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(200, text=_organic("https://example.org/a"))

    client = httpx.AsyncClient(base_url="https://api.brightdata.com",
                               transport=httpx.MockTransport(handler))
    bd = BrightDataClient(api_key="test", serp_zone="serp_z", client=client, retries=0)
    result = await SerpDiscoverySource(bd, max_queries=2).discover_plan(_plan())
    assert len(seen) == 2
    assert all(p["zone"] == "serp_z" and "gl=us" in p["url"] for p in seen)
    assert result.run_report.pages == 2
    assert any("capped" in w for w in result.run_report.warnings)


# ------------------------------------------------------------------ details
async def test_fetch_details_jsonld_page_direct_get():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=JSONLD_PAGE)

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    src = SerpDiscoverySource(serp=_serp_from({}), http=http)
    record = await src.fetch_details(SourceRef(provider="brightdata_serp", source_id="x",
                                               url="https://example.org/party"))
    assert record.provider == "web_jsonld" and record.source_mode == "live"
    assert record.payload["fetch_method"] == "direct_get"
    assert any("Unlocker not configured" in w for w in record.payload["detail_warnings"])
    events = normalize_detail(record, conference_id=CONF.id)
    assert len(events) == 1
    ev = events[0]
    assert ev.title == "Fictional Rooftop Happy Hour"
    assert ev.start_at is not None and ev.start_at.utcoffset().total_seconds() == -7 * 3600
    assert ev.venue.latitude == 37.80 and ev.venue.coordinate_precision == "exact"
    assert ev.is_free is True and ev.price_min == "0" and ev.currency == "USD"
    assert ev.status == "scheduled" and ev.conference_relation == "unknown"
    assert ev.organizer_names == ["Fictional Labs"]


async def test_fetch_details_without_jsonld_stays_unverified():
    http = httpx.AsyncClient(transport=httpx.MockTransport(
        lambda r: httpx.Response(200, text="<html>no data</html>")))
    src = SerpDiscoverySource(serp=_serp_from({}), http=http)
    with pytest.raises(DiscoveryError, match="unverified"):
        await src.fetch_details(SourceRef(provider="p", source_id="x",
                                          url="https://example.org/x"))


async def test_fetch_details_http_error_is_visible():
    http = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(503)))
    src = SerpDiscoverySource(serp=_serp_from({}), http=http)
    with pytest.raises(DiscoveryError, match="HTTP 503"):
        await src.fetch_details(SourceRef(provider="p", source_id="x",
                                          url="https://example.org/x"))


async def test_fetch_details_no_adapter_routes():
    src = SerpDiscoverySource(serp=_serp_from({}))
    with pytest.raises(DiscoveryError, match="no detail adapter"):
        await src.fetch_details(SourceRef(provider="p", source_id="x",
                                          url="https://www.linkedin.com/posts/abc"))


async def test_fetch_details_routes_to_sibling_adapter(monkeypatch):
    calls: list[SourceRef] = []

    class FakeLuma:
        def __init__(self, **_: object) -> None:
            pass

        async def fetch_details(self, ref: SourceRef) -> SourceRecord:
            calls.append(ref)
            raise RuntimeError("boom")

        async def aclose(self) -> None:
            pass

    src = SerpDiscoverySource(serp=_serp_from({}))
    monkeypatch.setattr(SerpDiscoverySource, "_adapter", staticmethod(lambda *a, **k: FakeLuma()))
    with pytest.raises(DiscoveryError, match="luma detail fetch failed"):
        await src.fetch_details(SourceRef(provider="p", source_id="x",
                                          url="https://lu.ma/fictional-mixer"))
    assert calls[0].provider == "luma" and calls[0].source_id == "fictional-mixer"


def test_extract_event_jsonld_ignores_bad_blocks():
    html = ('<script type="application/ld+json">{bad</script>'
            '<script type="application/ld+json">[{"@type":"Event","name":"A"}]</script>')
    assert [b["name"] for b in extract_event_jsonld(html)] == ["A"]


# ------------------------------------------------------------------ fixture
def test_fixture_requires_opt_in():
    with pytest.raises(DiscoveryError):
        fixture_plan()


async def test_fixture_is_labelled_and_parses():
    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert raw["source_mode"] == "fixture" and "SYNTHETIC" in raw["note"]
    result = await load_fixture(explicit_opt_in=True)
    assert result.run_report.source_mode == "fixture"
    assert any(w.startswith("FIXTURE:") for w in result.run_report.warnings)
    assert len(result.items) >= 10
    for item in result.items:
        assert item.source_mode == "fixture"
        assert item.payload["verified_event"] is False
        assert item.payload["discovered_by"][0]["snippet"] is None
        assert str(item.collected_at).startswith("2026-10-24")
    urls = [i.payload["canonical_url"] for i in result.items]
    assert len(urls) == len(set(urls))
    assert "https://luma.com/git-together" in urls  # lu.ma + luma.com variants merged
    assert "https://luma.com/discover" in urls  # kept, but routed to no adapter


# ------------------------------------------------------------------ pipeline
async def test_pipeline_events_only_from_details_and_never_official():
    src = fixture_source(explicit_opt_in=True)

    async def fake_fetch(ref: SourceRef) -> SourceRecord:
        if "amplitude.com" in str(ref.url):
            from conferge.events.discovery.jsonld import extract_event_jsonld as ex

            return SourceRecord(
                provider="web_jsonld", source_id="page:amp", source_mode="live",
                collected_at="2026-10-24T08:00:00+00:00", source_url=str(ref.url),
                payload={"jsonld_events": ex(JSONLD_PAGE)},
            )
        raise DiscoveryError("no schema.org Event JSON-LD on page; candidate kept unverified")

    src.fetch_details = fake_fetch  # type: ignore[method-assign]
    result = await run(CONF, source=src, plan=fixture_plan(explicit_opt_in=True),
                       sponsor_names=["Fictional Labs"], aliases=["Universe"])
    events = result.events.items
    assert len(events) == 1
    ev: Event = events[0]
    assert ev.conference_relation == "candidate"
    assert ev.relation_score is not None and ev.relation_score >= 0.5
    assert any("discovered via SERP query" in e for e in ev.relation_evidence)
    assert result.events.source_mode == "mixed"  # fixture candidates, live detail page
    assert result.events.status == "ok"
    statuses = {o.status for o in result.outcomes}
    assert "verified" in statuses and "unverified" in statuses and "skipped" in statuses
    linkedin_or_none = [o for o in result.outcomes if o.adapter == "none"]
    assert all(o.status == "skipped" for o in linkedin_or_none)
    assert result.groups and result.groups[0]["decision"] == "unique"


async def test_pipeline_detail_failure_degrades_status():
    src = fixture_source(explicit_opt_in=True)

    async def failing(ref: SourceRef) -> SourceRecord:
        raise DiscoveryError("page fetch HTTP 500")

    src.fetch_details = failing  # type: ignore[method-assign]
    result = await run(CONF, source=src, plan=fixture_plan(explicit_opt_in=True))
    assert result.events.items == []
    assert result.events.status == "degraded"
    assert result.events.reports[1].status == "degraded"
    assert any(o.status == "failed" for o in result.outcomes)


def test_anchor_conference_page_is_not_a_side_event():
    from conferge.events.discovery.pipeline import is_anchor_conference

    base = dict(id="e1", evidence=[])
    assert is_anchor_conference(Event(title="Github Universe 2026", **base), CONF)
    assert is_anchor_conference(Event(title="GitHub Universe", **base), CONF)
    assert not is_anchor_conference(Event(title="GitHub Universe Afterparty", **base), CONF)
