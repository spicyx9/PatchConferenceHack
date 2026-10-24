"""LinkedIn profile lookup (Bright Data SERP) and profile/company/posts datasets.

Lookup: `find_profile(name, company)` runs one Google query through the Bright Data
SERP zone, keeps only `linkedin.com/in/<slug>` hits, scores them deterministically
and returns a URL only when the best hit clears `THRESHOLD`, beats the runner-up by
`AMBIGUITY_MARGIN` and (when a company was supplied) mentions that company. A URL is
never guessed or built from a name.

Datasets: dataset ids come only from the environment, there are no hardcoded defaults.
Candidate ids seen in Bright Data docs, all UNVERIFIED (check them in the Bright Data
dashboard before setting the env vars):

- BRIGHTDATA_LINKEDIN_PROFILE_DATASET: gd_l1viktl72bvl7bjuj0 (LinkedIn people profiles)
- BRIGHTDATA_LINKEDIN_COMPANY_DATASET: gd_l1vikfnt1wgvvqz95w (LinkedIn company info)
- BRIGHTDATA_LINKEDIN_POSTS_DATASET: gd_lyy3tktm25m4avu764 (LinkedIn posts)
"""

from __future__ import annotations

import asyncio
import html
import json
import math
import os
import re
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import parse_qs, urlparse

from conferge.core.brightdata import BrightDataClient, BrightDataError
from conferge.core.schemas import SourceRecord
from conferge.people.models import ProfileCandidate, ProfileLookup
from conferge.people.taxonomy import fold

THRESHOLD = 0.7
AMBIGUITY_MARGIN = 0.05
PROVIDER = "brightdata:linkedin"
DEFAULT_CITY_HINTS: tuple[str, ...] = ("san francisco", "bay area", "new york")
MISSING_CREDENTIALS = "missing_credentials"

Sleep = Callable[[float], Awaitable[Any]]


class LinkedInUnavailable(RuntimeError):
    """Sanitized failure of a LinkedIn dataset call; never carries secrets or bodies."""


# ---------------------------------------------------------------------------
# Query and SERP parsing
# ---------------------------------------------------------------------------


def build_query(name: str, company: str | None) -> str:
    parts = [f'"{name.strip()}"']
    if company and company.strip():
        parts.append(f'"{company.strip()}"')
    parts.append("site:linkedin.com/in")
    return " ".join(parts)


def canonical_profile_url(url: str) -> str | None:
    """Return `https://www.linkedin.com/in/<slug>/` or None if not a profile URL."""
    try:
        parsed = urlparse(html.unescape(url.strip()))
    except ValueError:
        return None
    if parsed.scheme not in {"http", "https"}:
        return None
    host = (parsed.hostname or "").lower()
    if host != "linkedin.com" and not host.endswith(".linkedin.com"):
        return None
    segments = [s for s in parsed.path.split("/") if s]
    if len(segments) < 2 or segments[0].lower() != "in":
        return None
    # An encoded "?" or "#" (from a wrapped redirect) ends the slug.
    slug = re.split(r"%3f|%23", segments[1], flags=re.I)[0]
    if not re.fullmatch(r"[A-Za-z0-9\-_%.]+", slug):
        return None
    return f"https://www.linkedin.com/in/{slug}/"


def _unwrap_google(href: str) -> str:
    href = html.unescape(href)
    parsed = urlparse(href)
    if parsed.path == "/url" and (not parsed.hostname or "google" in parsed.hostname):
        query = parse_qs(parsed.query)
        target = (query.get("q") or query.get("url") or [""])[0]
        return target
    return href


_TAG_RE = re.compile(r"<[^>]+>")
_ANCHOR_RE = re.compile(r"<a\s[^>]*?href=\"([^\"]+)\"[^>]*>(.*?)</a>", re.I | re.S)
_H3_RE = re.compile(r"<h3[^>]*>(.*?)</h3>", re.I | re.S)
_BARE_URL_RE = re.compile(r"https?://(?:[a-z]{2,3}\.|www\.)?linkedin\.com/in/[A-Za-z0-9\-_.]+",
                          re.I)
_SCRIPT_RE = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.I | re.S)


def _text(fragment: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(_TAG_RE.sub(" ", fragment))).strip()


def _parse_json(data: Any) -> list[dict[str, Any]]:
    organic = data.get("organic") if isinstance(data, dict) else None
    hits: list[dict[str, Any]] = []
    for item in organic or []:
        if not isinstance(item, dict):
            continue
        link = item.get("link") or item.get("url")
        if not isinstance(link, str):
            continue
        hits.append({
            "url": link,
            "title": item.get("title") if isinstance(item.get("title"), str) else None,
            "snippet": item.get("description") if isinstance(item.get("description"), str)
            else None,
        })
    return hits


def _parse_html(text: str) -> list[dict[str, Any]]:
    body = _SCRIPT_RE.sub(" ", text)
    hits: list[dict[str, Any]] = []
    anchors = list(_ANCHOR_RE.finditer(body))
    for index, match in enumerate(anchors):
        target = _unwrap_google(match.group(1))
        if canonical_profile_url(target) is None:
            continue
        inner = match.group(2)
        h3 = _H3_RE.search(inner)
        title = _text(h3.group(1) if h3 else inner) or None
        # Cheap snippet: text after this anchor up to the next anchor, capped.
        end = anchors[index + 1].start() if index + 1 < len(anchors) else len(body)
        snippet = _text(body[match.end():min(end, match.end() + 2000)])[:400] or None
        hits.append({"url": target, "title": title, "snippet": snippet})
    for bare in _BARE_URL_RE.finditer(body):
        hits.append({"url": bare.group(0), "title": None, "snippet": None})
    return hits


def parse_serp(text: str) -> list[dict[str, Any]]:
    """Extract LinkedIn profile hits from brd_json JSON or raw Google HTML.

    Returns dicts with url (canonical), title, snippet; deduped, first occurrence wins
    but a later hit can fill a missing title/snippet.
    """
    raw: list[dict[str, Any]]
    stripped = text.lstrip()
    raw = []
    if stripped.startswith("{"):
        try:
            raw = _parse_json(json.loads(stripped))
        except json.JSONDecodeError:
            raw = []
    if not raw:
        raw = _parse_html(text)
    seen: dict[str, dict[str, Any]] = {}
    for hit in raw:
        url = canonical_profile_url(hit["url"])
        if url is None:
            continue
        if url in seen:
            prev = seen[url]
            prev["title"] = prev["title"] or hit.get("title")
            prev["snippet"] = prev["snippet"] or hit.get("snippet")
            continue
        seen[url] = {"url": url, "title": hit.get("title"), "snippet": hit.get("snippet")}
    return list(seen.values())


# ---------------------------------------------------------------------------
# Scoring and lookup
# ---------------------------------------------------------------------------


def _contains_phrase(haystack: str, phrase: str) -> bool:
    if not phrase:
        return False
    return re.search(rf"(?<![a-z0-9]){re.escape(phrase)}(?![a-z0-9])", haystack) is not None


def _slug_of(url: str) -> str:
    segments = [s for s in urlparse(url).path.split("/") if s]
    return segments[-1] if segments else ""


def score_candidate(
    name: str,
    company: str | None,
    hit: dict[str, Any],
    city_hints: Iterable[str] = DEFAULT_CITY_HINTS,
) -> ProfileCandidate:
    """Deterministic identity score for one SERP hit (see module docstring)."""
    title = fold(hit.get("title") or "")
    snippet = fold(hit.get("snippet") or "")
    slug = fold(_slug_of(str(hit["url"])))
    slug_words = re.sub(r"[^a-z0-9]+", " ", slug)
    full = fold(name)
    tokens = [t for t in re.split(r"[^a-z0-9]+", full) if t]
    score = 0.0
    reasons: list[str] = []

    if _contains_phrase(title, full):
        score += 0.5
        reasons.append("+0.5 exact full name in title")
    elif tokens and all(
        _contains_phrase(title, t) or _contains_phrase(slug_words, t) for t in tokens
    ):
        score += 0.25
        reasons.append("+0.25 all name tokens in title or slug")

    if company:
        comp = fold(company)
        if comp and (_contains_phrase(title, comp) or _contains_phrase(snippet, comp)):
            score += 0.3
            reasons.append("+0.3 company in title or snippet")
        else:
            reasons.append("+0 company not found in title or snippet")
    else:
        reasons.append("+0 no company supplied (name-only match is weak)")

    city = next((c for c in city_hints if _contains_phrase(snippet, fold(c))), None)
    if city:
        score += 0.1
        reasons.append(f"+0.1 city hint '{city}' in snippet")

    if len(tokens) >= 2 and tokens[0] in slug and tokens[-1] in slug:
        score += 0.1
        reasons.append("+0.1 slug contains first and last name")

    score = round(min(score, 1.0), 4)
    return ProfileCandidate(
        url=hit["url"], title=hit.get("title"), snippet=hit.get("snippet"),
        score=score, reasons=reasons,
    )


def _company_matched(candidate: ProfileCandidate) -> bool:
    return any(r.startswith("+0.3 company") for r in candidate.reasons)


def sanitize_error(exc: BaseException) -> str:
    message = str(exc) or exc.__class__.__name__
    lowered = message.lower()
    if "key missing" in lowered or "not configured" in lowered or "api_key" in lowered:
        return f"{MISSING_CREDENTIALS}: {message}"
    return message[:200]


async def find_profile(
    client: BrightDataClient, name: str, company: str | None,
    *, city_hints: Iterable[str] = DEFAULT_CITY_HINTS,
) -> ProfileLookup:
    """Look up one LinkedIn profile URL; never guesses a URL."""
    query = build_query(name, company)
    try:
        text = await client.serp(query)
    except BrightDataError as exc:
        return ProfileLookup(
            name=name, company=company, query=query, status="failed", source_mode="live",
            collected_at=datetime.now(timezone.utc), error=sanitize_error(exc),
        )
    collected_at = datetime.now(timezone.utc)
    hints = tuple(city_hints)
    candidates = sorted(
        (score_candidate(name, company, hit, hints) for hit in parse_serp(text)),
        key=lambda c: c.score, reverse=True,
    )
    if not candidates:
        return ProfileLookup(
            name=name, company=company, query=query, status="degraded", source_mode="live",
            collected_at=collected_at, error="no linkedin profile in search results",
        )
    best = candidates[0]
    runner_up = candidates[1].score if len(candidates) > 1 else 0.0
    error: str | None = None
    if best.score < THRESHOLD:
        error = f"best candidate score {best.score} below threshold {THRESHOLD}"
    elif best.score - runner_up < AMBIGUITY_MARGIN - 1e-9:
        error = f"ambiguous: top candidates {best.score} and {runner_up}"
    elif not company:
        # Name + city alone can reach 0.7 for a namesake; without a company the
        # identity cannot be checked, so the URL is never attached.
        error = "no company supplied: name-only match is not attached"
    elif not _company_matched(best):
        error = "company supplied but not found on best candidate"
    if error:
        return ProfileLookup(
            name=name, company=company, query=query, status="degraded", source_mode="live",
            collected_at=collected_at, candidates=candidates, confidence=best.score,
            error=error,
        )
    return ProfileLookup(
        name=name, company=company, query=query, status="ok", source_mode="live",
        collected_at=collected_at, candidates=candidates, linkedin_url=best.url,
        confidence=best.score,
    )


# ---------------------------------------------------------------------------
# Datasets
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LinkedInDatasets:
    profile: str | None = None
    company: str | None = None
    posts: str | None = None

    @classmethod
    def from_env(cls) -> LinkedInDatasets:
        return cls(
            profile=os.getenv("BRIGHTDATA_LINKEDIN_PROFILE_DATASET") or None,
            company=os.getenv("BRIGHTDATA_LINKEDIN_COMPANY_DATASET") or None,
            posts=os.getenv("BRIGHTDATA_LINKEDIN_POSTS_DATASET") or None,
        )


def _records(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return [r for r in data if isinstance(r, dict)]
    if isinstance(data, dict):
        return [data]
    return []


async def _collect(
    client: BrightDataClient, dataset_id: str | None, env_name: str, url: str, *,
    poll_interval: float, timeout_s: float, sleep: Sleep, limit_per_input: int | None,
) -> tuple[list[dict[str, Any]], str | None]:
    if not dataset_id:
        raise LinkedInUnavailable(f"{MISSING_CREDENTIALS}: {env_name} not set")
    try:
        out = await client.scrape_dataset(
            dataset_id, [{"url": url}], method=None, limit_per_input=limit_per_input,
        )
        snapshot_id = out.snapshot_id
        polls = max(1, math.ceil(timeout_s / poll_interval)) if poll_interval > 0 else 1
        while out.status == "running":
            if polls <= 0 or snapshot_id is None:
                raise LinkedInUnavailable(
                    f"snapshot {snapshot_id} not ready after {timeout_s:.0f}s"
                )
            polls -= 1
            await sleep(poll_interval)
            out = await client.snapshot_results(snapshot_id)
    except BrightDataError as exc:
        raise LinkedInUnavailable(sanitize_error(exc)) from exc
    records = _records(out.data)
    errors = [r for r in records if r.get("error")]
    if errors:
        code = errors[0].get("error_code") or "record_error"
        raise LinkedInUnavailable(f"Bright Data dataset returned an error record ({code})")
    if not records:
        raise LinkedInUnavailable("Bright Data dataset returned no records")
    return records, snapshot_id


def _record(url: str, payload: dict[str, Any], snapshot_id: str | None) -> SourceRecord:
    return SourceRecord(
        provider=PROVIDER, source_id=_slug_of(url) or url, source_mode="live",
        collected_at=datetime.now(timezone.utc), payload=payload, source_url=url,
        request_id=snapshot_id,
    )


async def fetch_profile(
    client: BrightDataClient, url: str, *, dataset_id: str | None = None,
    poll_interval: float = 5.0, timeout_s: float = 150.0, sleep: Sleep = asyncio.sleep,
) -> SourceRecord:
    dataset_id = dataset_id or LinkedInDatasets.from_env().profile
    records, snapshot_id = await _collect(
        client, dataset_id, "BRIGHTDATA_LINKEDIN_PROFILE_DATASET", url,
        poll_interval=poll_interval, timeout_s=timeout_s, sleep=sleep, limit_per_input=None,
    )
    return _record(url, records[0], snapshot_id)


async def fetch_company(
    client: BrightDataClient, url: str, *, dataset_id: str | None = None,
    poll_interval: float = 5.0, timeout_s: float = 150.0, sleep: Sleep = asyncio.sleep,
) -> SourceRecord:
    dataset_id = dataset_id or LinkedInDatasets.from_env().company
    records, snapshot_id = await _collect(
        client, dataset_id, "BRIGHTDATA_LINKEDIN_COMPANY_DATASET", url,
        poll_interval=poll_interval, timeout_s=timeout_s, sleep=sleep, limit_per_input=None,
    )
    return _record(url, records[0], snapshot_id)


async def fetch_posts(
    client: BrightDataClient, url: str, limit: int = 10, *, dataset_id: str | None = None,
    poll_interval: float = 5.0, timeout_s: float = 150.0, sleep: Sleep = asyncio.sleep,
) -> SourceRecord:
    dataset_id = dataset_id or LinkedInDatasets.from_env().posts
    records, snapshot_id = await _collect(
        client, dataset_id, "BRIGHTDATA_LINKEDIN_POSTS_DATASET", url,
        poll_interval=poll_interval, timeout_s=timeout_s, sleep=sleep, limit_per_input=limit,
    )
    return _record(url, {"posts": records[:limit]}, snapshot_id)
