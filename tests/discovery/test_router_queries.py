"""Offline tests for URL routing and query generation (window 04)."""

from __future__ import annotations

from datetime import date

import pytest

from conferge.events.discovery.queries import QueryPlan, build_queries
from conferge.events.discovery.router import canonicalize, route_url, unwrap_redirect


@pytest.mark.parametrize(
    ("url", "platform", "kind", "adapter", "pid"),
    [
        ("https://lu.ma/git-together?utm_source=x", "luma", "event_or_calendar", "luma",
         "git-together"),
        ("https://luma.com/discover", "luma", "listing", "none", None),
        ("https://www.eventbrite.com/e/ai-night-tickets-2003686507281", "eventbrite",
         "event_page", "eventbrite", "2003686507281"),
        ("https://www.eventbrite.sg/e/ai-careers-tickets-2002485891206", "eventbrite",
         "event_page", "eventbrite", "2002485891206"),
        ("https://www.eventbrite.com/o/some-org-123", "eventbrite", "profile", "none", None),
        ("https://partiful.com/e/AbC123", "partiful", "event_page", "partiful", "AbC123"),
        ("https://m.facebook.com/events/123456789/", "facebook", "event_page",
         "facebook_events", "123456789"),
        ("https://www.facebook.com/SomeSponsor", "facebook", "profile", "none", None),
        ("https://www.meetup.com/sf-devs/events/301234567/", "meetup", "event_page", "jsonld",
         "301234567"),
        ("https://www.linkedin.com/events/universe-mixer-7250000000000000000/", "linkedin",
         "event_page", "none", "7250000000000000000"),
        ("https://githubuniverse.com/program", "official", "listing", "official", None),
        ("https://conferenceparties.com/github26/", "aggregator", "listing", "aggregators",
         None),
        ("https://x.com/someone/status/1", "social", "post", "none", None),
        ("https://amplitude.com/2026-10-github-universe#afterparty", "generic", "other",
         "jsonld", None),
    ],
)
def test_route_url(url, platform, kind, adapter, pid):
    route = route_url(url)
    assert (route.platform, route.page_kind, route.adapter, route.platform_id) == (
        platform, kind, adapter, pid
    )
    assert route.url == url
    assert route.reason


def test_canonicalize_suppresses_duplicates():
    variants = [
        "https://lu.ma/git-together",
        "http://www.luma.com/git-together/",
        "https://luma.com/git-together?utm_campaign=a&fbclid=b#top",
        "https://www.google.com/url?q=https://lu.ma/git-together&sa=U",
    ]
    assert {canonicalize(v) for v in variants} == {"https://luma.com/git-together"}


def test_canonicalize_keeps_meaningful_query_and_rejects_non_http():
    assert canonicalize("https://example.org/e?id=7&utm_source=x") == "https://example.org/e?id=7"
    with pytest.raises(ValueError):
        canonicalize("mailto:someone@example.org")
    with pytest.raises(ValueError):
        route_url("/relative/path")


def test_unwrap_redirect_only_for_search_hosts():
    assert unwrap_redirect("/url?q=https://a.example/x&sa=U") == "https://a.example/x"
    assert unwrap_redirect("https://site.example/url?q=https://b.example") == (
        "https://site.example/url?q=https://b.example"
    )


def _plan(**kw) -> QueryPlan:
    base = dict(
        city="San Francisco", conference_name="GitHub Universe", aliases=["Universe"],
        venue="Fort Mason Center", start_date=date(2026, 10, 28), end_date=date(2026, 10, 29),
        sponsors=["Amplitude", "Rubrik"], topics=["AI agents"],
    )
    base.update(kw)
    return QueryPlan(**base)


def test_query_families_cover_acceptance():
    queries = build_queries(_plan())
    families = {q.family for q in queries}
    assert {"conference", "host", "venue_date", "platform", "goal"} <= families
    texts = [q.text for q in queries]
    assert any(t.startswith('"GitHub Universe" San Francisco afterparty') for t in texts)
    assert any(t.startswith("Amplitude San Francisco October 2026") for t in texts)
    assert "site:luma.com San Francisco October 28 2026" in texts
    # venue/date queries never carry conference keywords
    for q in queries:
        if q.family == "venue_date":
            assert "universe" not in q.text.casefold()
            assert "github" not in q.text.casefold()
    assert all(q.reason for q in queries)


def test_queries_deduplicated_and_deterministic():
    plan = _plan(sponsors=["Amplitude", "amplitude", "Rubrik"], hosts=["Rubrik"])
    first, second = build_queries(plan), build_queries(plan)
    assert first == second
    texts = [q.text.casefold() for q in first]
    assert len(texts) == len(set(texts))


def test_queries_without_conference_still_produce_city_queries():
    queries = build_queries(QueryPlan(city="San Francisco", start_date=date(2026, 10, 28)))
    assert queries
    assert {q.family for q in queries} <= {"venue_date", "platform"}


def test_platform_days_bounded():
    queries = build_queries(_plan(max_platform_days=2))
    luma = [q for q in queries if q.text.startswith("site:luma.com")]
    assert len(luma) == 2
