"""Public-profile enrichment for window 07 (people).

- `GitHubEnricher` reads the public GitHub REST API (user + recent repos) into a
  `SourceRecord`. A token is optional (raises the rate limit) and is never logged or
  included in error messages.
- `apply_github` merges a GitHub record into a `PersonProfile` behind an identity guard
  and never overwrites non-null fields.
- `enrich_topics` derives topics/roles from the person's own published text.
- `investor_flag` is a best-effort keyword heuristic for companies.

Nothing here writes to the graph; callers go through `GraphStore`.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from types import TracebackType
from typing import Any
from urllib.parse import urlparse

import httpx

from conferge.core.schemas import Company, SourceEvidence, SourceRecord
from conferge.people.models import PersonProfile
from conferge.people.taxonomy import (
    TopicExtractor,
    extract_topics,
    fold,
    roles_from_title,
    topics_from_text,
)

GITHUB_API = "https://api.github.com"
PROVIDER = "github:api"
USER_AGENT = "conferge-w07"

_LOGIN_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$")
# First path segments on github.com that are not user logins.
_RESERVED = frozenset({
    "about", "account", "apps", "blog", "collections", "contact", "customer-stories",
    "dashboard", "enterprise", "events", "explore", "features", "gist", "issues",
    "login", "logout", "marketplace", "new", "notifications", "orgs", "organizations",
    "pricing", "pulls", "readme", "search", "security", "settings", "site", "sponsors",
    "stars", "team", "teams", "topics", "trending", "users", "join", "signup", "codespaces",
    "copilot", "discussions", "resources", "solutions", "premium-support", "why-github",
})
_USER_FIELDS = (
    "login", "name", "company", "blog", "location", "bio", "public_repos", "followers",
    "html_url", "type",
)
_REPO_FIELDS = ("name", "description", "language", "topics", "stargazers_count", "fork")


class EnrichmentError(Exception):
    """Visible enrichment failure. Messages never contain credentials."""


def github_login(url_or_handle: str | None) -> str | None:
    """Return the login from `https://github.com/<login>` or a bare handle, else None.

    Reserved first segments (orgs/, topics/, sponsors/, ...) are rejected. A trailing
    slash is accepted; deeper paths (repos) are rejected so a repo URL is not mistaken
    for a person.
    """
    if not url_or_handle:
        return None
    text = url_or_handle.strip()
    if not text:
        return None
    if "/" in text or "." in text:
        if "://" not in text:
            text = "https://" + text
        parsed = urlparse(text)
        host = (parsed.hostname or "").lower()
        if host not in {"github.com", "www.github.com"}:
            return None
        parts = [p for p in parsed.path.split("/") if p]
        if len(parts) != 1:
            return None
        candidate = parts[0]
    else:
        candidate = text.removeprefix("@")
    if candidate.lower() in _RESERVED:
        return None
    if not _LOGIN_RE.match(candidate) or candidate.endswith("-") or "--" in candidate:
        return None
    return candidate


def _content_hash(payload: dict[str, Any]) -> str:
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


class GitHubEnricher:
    """Async client for public GitHub user data."""

    def __init__(self, client: httpx.AsyncClient | None = None, token: str | None = None):
        self._token = token if token is not None else (os.environ.get("GITHUB_TOKEN") or None)
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(base_url=GITHUB_API, timeout=20.0)

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": USER_AGENT,
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def __aenter__(self) -> GitHubEnricher:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        url = f"{GITHUB_API}{path}"
        try:
            resp = await self._client.get(url, params=params, headers=self._headers())
        except httpx.HTTPError:
            # Do not chain: the original exception may carry request headers.
            raise EnrichmentError("github: network error") from None
        if resp.status_code == 404:
            raise EnrichmentError("github: user not found")
        if resp.status_code == 429 or (
            resp.status_code == 403 and resp.headers.get("x-ratelimit-remaining") == "0"
        ):
            raise EnrichmentError("github: rate_limited")
        if resp.status_code == 403:
            raise EnrichmentError("github: forbidden")
        if resp.status_code >= 400:
            raise EnrichmentError(f"github: http {resp.status_code}")
        try:
            return resp.json()
        except ValueError:
            raise EnrichmentError("github: invalid json") from None

    async def fetch_user(self, login: str) -> SourceRecord:
        """Fetch a public user and their 30 most recently pushed repos (non-forks kept)."""
        valid = github_login(login)
        if valid is None:
            raise EnrichmentError("github: invalid login")
        user = await self._get(f"/users/{valid}")
        repos = await self._get(f"/users/{valid}/repos", {"per_page": 30, "sort": "pushed"})
        if not isinstance(user, dict) or not isinstance(repos, list):
            raise EnrichmentError("github: unexpected payload")
        user_sub = {k: user.get(k) for k in _USER_FIELDS}
        repo_subs = [
            {k: (r.get(k) if k != "topics" else list(r.get("topics") or [])) for k in _REPO_FIELDS}
            for r in repos
            if isinstance(r, dict) and not r.get("fork")
        ]
        payload = {"user": user_sub, "repos": repo_subs}
        canonical_login = str(user_sub.get("login") or valid)
        return SourceRecord(
            provider=PROVIDER,
            source_id=f"github:{canonical_login.lower()}",
            source_mode="live",
            collected_at=datetime.now(timezone.utc),
            payload=payload,
            source_url=user_sub.get("html_url") or f"https://github.com/{canonical_login}",
            content_hash=_content_hash(payload),
        )


def _merge(existing: list[str], extra: list[str]) -> list[str]:
    out = list(existing)
    for item in extra:
        if item not in out:
            out.append(item)
    return out


def apply_github(profile: PersonProfile, record: SourceRecord) -> tuple[PersonProfile, bool, str]:
    """Merge a GitHub record into a profile. Returns (profile, applied, reason).

    Identity guard: applied only if the GitHub display name folds equal to the person
    name, or the person already carries a github_url for this login (source-declared).
    Non-null fields are never overwritten; roles are never inferred from repos.
    """
    user = record.payload.get("user") or {}
    repos = record.payload.get("repos") or []
    login = user.get("login")
    if not login:
        return profile, False, "record has no login"
    person = profile.person
    declared_login = github_login(str(person.github_url)) if person.github_url else None
    declared = declared_login is not None and declared_login.lower() == str(login).lower()
    gh_name = user.get("name")
    name_match = bool(gh_name) and fold(str(gh_name)) == fold(person.name)
    if person.github_url and not declared:
        return profile, False, "person github_url points to a different login"
    if not (declared or name_match):
        return profile, False, "github name does not match person name"

    bio = user.get("bio")
    texts: list[str | None] = [bio]
    for repo in repos:
        texts.append(repo.get("description"))
        texts.append(" ".join(repo.get("topics") or []))
        texts.append(repo.get("language"))
    new_topics = topics_from_text(*texts)

    update: dict[str, Any] = {
        "topics": _merge(person.topics, new_topics),
        "evidence": [
            *person.evidence,
            SourceEvidence(
                provider=PROVIDER,
                source_mode=record.source_mode,
                source_url=record.source_url,
                collected_at=record.collected_at,
                source_record_id=record.source_id,
                confidence=1.0 if declared else 0.8,
            ),
        ],
    }
    if person.github_url is None and user.get("html_url"):
        update["github_url"] = user["html_url"]
    if person.bio is None and bio:
        update["bio"] = bio
    # Validate (model_copy(update=...) would skip URL/literal validation).
    new_person = type(person).model_validate({**person.model_dump(), **update})
    reason = "source-declared github_url" if declared else "name match"
    return profile.model_copy(update={"person": new_person}), True, reason


async def enrich_topics(
    profile: PersonProfile, extractor: TopicExtractor | None = None
) -> PersonProfile:
    """Add topics from bio, title and talk titles; set roles from title if none.

    The optional extractor's output is clipped to the taxonomy; failures fall back to
    keyword matching (see `taxonomy.extract_topics`).
    """
    person = profile.person
    topics, _method = await extract_topics(
        [person.bio, person.title, *profile.talk_titles], extractor
    )
    update: dict[str, Any] = {"topics": _merge(person.topics, topics)}
    if not person.roles:
        roles = roles_from_title(person.title)
        if roles:
            update["roles"] = roles
    new_person = type(person).model_validate({**person.model_dump(), **update})
    return profile.model_copy(update={"person": new_person})


_INVESTOR_RE = re.compile(
    r"(?<![a-z0-9])(?:venture capital|ventures?|capital|vc fund|venture fund|vc)(?![a-z0-9])"
)
INVESTOR_CATEGORY = "investor_heuristic"


def investor_flag(company: Company, evidence_text: str | None = None) -> Company:
    """Heuristic: mark a company as an investor from name/categories/evidence keywords.

    Sets `is_investor=True` and adds the `investor_heuristic` category only when
    venture/capital/vc keywords appear on word boundaries (e.g. "Example Ventures").
    Never sets False and never overwrites an existing non-null `is_investor`.
    This is a guess, not verified fund data; "capital" can produce false positives.
    """
    if company.is_investor is not None:
        return company
    blob = fold(" ".join([company.name, *company.categories, evidence_text or ""]))
    if not _INVESTOR_RE.search(blob):
        return company
    categories = _merge(company.categories, [INVESTOR_CATEGORY])
    return company.model_copy(update={"is_investor": True, "categories": categories})
