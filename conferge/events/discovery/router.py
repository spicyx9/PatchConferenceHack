"""Domain router for SERP candidate URLs (window 04).

A routed URL is still only a candidate: the route says which downstream adapter
should verify it (Luma, Eventbrite, Partiful, Facebook, Meetup, official site,
aggregator or the generic JSON-LD extractor). Nothing here asserts that an event
exists or is related to the conference.
"""

from __future__ import annotations

import re
from typing import Literal
from urllib.parse import parse_qsl, unquote, urlencode, urlsplit, urlunsplit

from pydantic import BaseModel, ConfigDict

Platform = Literal[
    "luma", "eventbrite", "partiful", "facebook", "meetup", "linkedin", "official",
    "aggregator", "social", "search_engine", "generic",
]
PageKind = Literal["event_page", "event_or_calendar", "listing", "profile", "post", "other"]
Adapter = Literal[
    "luma", "eventbrite", "partiful", "facebook_events", "official", "aggregators",
    "jsonld", "none",
]

_TRACKING_PARAMS = re.compile(
    r"^(utm_[a-z]+|fbclid|gclid|gbraid|wbraid|mc_[a-z]+|ref|ref_src|igshid|si|_hsenc|_hsmi"
    r"|aff|source|tk)$",
    re.IGNORECASE,
)
_LUMA_RESERVED = frozenset({
    "", "discover", "signin", "login", "home", "explore", "create", "pricing", "user", "u",
    "calendar", "settings", "about", "terms", "privacy", "help", "ios", "android", "sf",
    "san-francisco", "nyc", "ai",
})
_OFFICIAL_HOSTS = ("githubuniverse.com", "reg.githubuniverse.com")
_AGGREGATOR_HOSTS = ("conferenceparties.com", "raidandev.org", "reinventradar.com")
_SOCIAL_HOSTS = ("x.com", "twitter.com", "instagram.com", "threads.net", "bsky.app")
_SEARCH_HOSTS = ("google.com", "bing.com", "duckduckgo.com")


class Route(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    url: str
    canonical_url: str
    host: str
    platform: Platform
    page_kind: PageKind
    adapter: Adapter
    platform_id: str | None = None
    reason: str


def unwrap_redirect(url: str) -> str:
    """Return the target of a Google `/url?q=` style redirect, else the URL itself."""
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if parts.path in {"/url", "/link"} and (not host or host.endswith(_SEARCH_HOSTS)):
        params = dict(parse_qsl(parts.query))
        target = params.get("q") or params.get("url")
        if target and target.startswith(("http://", "https://")):
            return unquote(target)
    return url


def canonicalize(url: str) -> str:
    """Stable URL key: https, lowercase host without www, lu.ma -> luma.com,
    tracking parameters and fragments removed, no trailing slash."""
    url = unwrap_redirect(url.strip())
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        raise ValueError("not an absolute http(s) URL")
    host = parts.hostname.lower()
    if host.startswith("www."):
        host = host[4:]
    if host in {"lu.ma", "m.luma.com"}:
        host = "luma.com"
    if host in {"m.facebook.com", "web.facebook.com", "mbasic.facebook.com"}:
        host = "facebook.com"
    if host.startswith("m.") and host[2:] in {"eventbrite.com", "meetup.com"}:
        host = host[2:]
    path = re.sub(r"/{2,}", "/", parts.path or "/")
    if len(path) > 1:
        path = path.rstrip("/")
    query = urlencode(sorted(
        (k, v) for k, v in parse_qsl(parts.query, keep_blank_values=False)
        if not _TRACKING_PARAMS.match(k)
    ))
    return urlunsplit(("https", host, path if path != "/" else "", query, ""))


def _host_is(host: str, *domains: str) -> bool:
    return any(host == d or host.endswith("." + d) for d in domains)


def route_url(url: str) -> Route:
    """Classify a candidate URL by platform and page kind. Raises ValueError on
    non-http(s) input."""
    canonical = canonicalize(url)
    parts = urlsplit(canonical)
    host = parts.hostname or ""
    segments = [s for s in parts.path.split("/") if s]

    def make(platform: Platform, kind: PageKind, adapter: Adapter, reason: str,
             platform_id: str | None = None) -> Route:
        return Route(url=url, canonical_url=canonical, host=host, platform=platform,
                     page_kind=kind, adapter=adapter, platform_id=platform_id, reason=reason)

    if _host_is(host, "luma.com"):
        if len(segments) == 1 and segments[0].lower() not in _LUMA_RESERVED:
            return make("luma", "event_or_calendar", "luma",
                        "luma.com single-segment slug (event page or calendar)", segments[0])
        if len(segments) >= 2 and segments[0] == "e":
            return make("luma", "event_page", "luma", "luma.com/e/<id>", segments[1])
        return make("luma", "listing", "none", "luma.com non-event path")

    if re.match(r"^(?:[a-z0-9-]+\.)?eventbrite\.[a-z.]{2,6}$", host):
        if len(segments) >= 2 and segments[0] == "e":
            match = re.search(r"(\d{6,})$", segments[1])
            return make("eventbrite", "event_page", "eventbrite", "eventbrite.com/e/<slug>-<id>",
                        match.group(1) if match else None)
        if segments and segments[0] == "o":
            return make("eventbrite", "profile", "none", "eventbrite organizer page")
        return make("eventbrite", "listing", "none", "eventbrite listing/search page")

    if _host_is(host, "partiful.com"):
        if len(segments) >= 2 and segments[0] == "e":
            return make("partiful", "event_page", "partiful", "partiful.com/e/<id>", segments[1])
        return make("partiful", "listing", "none", "partiful non-event path")

    if _host_is(host, "facebook.com", "fb.me"):
        if len(segments) >= 2 and segments[0] == "events" and segments[1].isdigit():
            return make("facebook", "event_page", "facebook_events", "facebook.com/events/<id>",
                        segments[1])
        if segments and segments[0] == "events":
            return make("facebook", "listing", "none", "facebook events listing")
        return make("facebook", "profile", "none", "facebook page (possible host page)")

    if _host_is(host, "meetup.com"):
        if len(segments) >= 3 and segments[1] == "events" and segments[2].isdigit():
            return make("meetup", "event_page", "jsonld",
                        "meetup.com/<group>/events/<id> (Web Unlocker + JSON-LD)", segments[2])
        if len(segments) == 1:
            return make("meetup", "profile", "none", "meetup group page")
        return make("meetup", "listing", "none", "meetup listing page")

    if _host_is(host, "linkedin.com"):
        if len(segments) >= 2 and segments[0] == "events":
            match = re.search(r"(\d{6,})$", segments[1])
            return make("linkedin", "event_page", "none",
                        "linkedin.com/events (login wall; no adapter tonight)",
                        match.group(1) if match else segments[1])
        if segments and segments[0] == "posts":
            return make("linkedin", "post", "none", "linkedin post: signal, not an event")
        return make("linkedin", "profile", "none", "linkedin profile/company page")

    if _host_is(host, *_OFFICIAL_HOSTS):
        return make("official", "listing", "official", "official conference site")

    if _host_is(host, *_AGGREGATOR_HOSTS):
        return make("aggregator", "listing", "aggregators", "conference party aggregator")

    if _host_is(host, *_SOCIAL_HOSTS):
        kind: PageKind = "post" if "status" in segments or "p" in segments else "profile"
        return make("social", kind, "none", "social post/profile: signal, not an event")

    if _host_is(host, *_SEARCH_HOSTS):
        return make("search_engine", "other", "none", "search engine internal link")

    return make("generic", "other", "jsonld",
                "independent site: Web Unlocker + schema.org Event JSON-LD if present")
