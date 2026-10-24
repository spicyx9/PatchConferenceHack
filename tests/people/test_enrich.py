from datetime import datetime, timezone

import httpx
import pytest

from conferge.core.schemas import Company, Person, SourceRecord
from conferge.people.enrich import (
    GITHUB_API,
    EnrichmentError,
    GitHubEnricher,
    apply_github,
    enrich_topics,
    github_login,
    investor_flag,
)
from conferge.people.models import PersonProfile

TOKEN = "ghp_secret"

USER = {
    "login": "avery-example",
    "name": "Avery Example",
    "company": "@example-co",
    "blog": "https://example.org",
    "location": "San Francisco",
    "bio": None,
    "public_repos": 3,
    "followers": 10,
    "html_url": "https://github.com/avery-example",
    "type": "User",
    "email": "should-not-be-kept@example.org",
}
REPOS = [
    {"name": "agent-kit", "description": "An MCP server for coding agents", "language": "Python",
     "topics": ["model-context-protocol"], "stargazers_count": 5, "fork": False,
     "private_field": "dropped"},
    {"name": "forked-thing", "description": "Kubernetes operator", "language": "Go",
     "topics": [], "stargazers_count": 0, "fork": True},
    {"name": "scanner", "description": None, "language": "Rust",
     "topics": ["secret-scanning", "devsecops"], "stargazers_count": 1, "fork": False},
]


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(base_url=GITHUB_API, transport=httpx.MockTransport(handler))


def _ok_handler(calls):
    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(req)
        if req.url.path == "/users/avery-example":
            return httpx.Response(200, json=USER)
        if req.url.path == "/users/avery-example/repos":
            return httpx.Response(200, json=REPOS)
        return httpx.Response(404, json={"message": "Not Found"})
    return handler


def _profile(**kw) -> PersonProfile:
    base = {"id": "person:avery-example", "name": "Avery Example"}
    base.update(kw)
    return PersonProfile(person=Person(**base))


def _record(user=None, repos=None) -> SourceRecord:
    return SourceRecord(
        provider="github:api",
        source_id="github:avery-example",
        source_mode="live",
        collected_at=datetime(2026, 10, 24, tzinfo=timezone.utc),
        source_url="https://github.com/avery-example",
        payload={"user": user or {k: USER[k] for k in ("login", "name", "bio", "html_url")},
                 "repos": repos if repos is not None else [
                     {"name": "agent-kit", "description": "An MCP server for coding agents",
                      "language": "Python", "topics": [], "stargazers_count": 1,
                      "fork": False}]},
    )


@pytest.mark.parametrize("value,expected", [
    ("https://github.com/avery-example", "avery-example"),
    ("https://github.com/avery-example/", "avery-example"),
    ("http://www.github.com/Avery-Example", "Avery-Example"),
    ("github.com/avery-example", "avery-example"),
    ("avery-example", "avery-example"),
    ("@avery-example", "avery-example"),
])
def test_github_login_valid(value, expected):
    assert github_login(value) == expected


@pytest.mark.parametrize("value", [
    None, "", "https://github.com/orgs/example", "https://github.com/topics/mcp",
    "https://github.com/sponsors/avery-example", "https://github.com/sponsors",
    "https://github.com/avery-example/agent-kit", "https://gitlab.com/avery-example",
    "-avery", "avery-", "avery--example", "a" * 40, "avery_example",
    "https://github.com/",
])
def test_github_login_invalid(value):
    assert github_login(value) is None


@pytest.mark.asyncio
async def test_fetch_user_payload_and_fork_filtering():
    calls: list[httpx.Request] = []
    async with GitHubEnricher(client=_client(_ok_handler(calls)), token=TOKEN) as gh:
        rec = await gh.fetch_user("avery-example")
    assert rec.provider == "github:api"
    assert rec.source_id == "github:avery-example"
    assert rec.source_mode == "live"
    assert rec.collected_at.tzinfo is not None
    assert str(rec.source_url) == "https://github.com/avery-example"
    assert rec.content_hash and len(rec.content_hash) == 64
    assert "email" not in rec.payload["user"]
    assert rec.payload["user"]["name"] == "Avery Example"
    assert [r["name"] for r in rec.payload["repos"]] == ["agent-kit", "scanner"]
    assert set(rec.payload["repos"][0]) == {
        "name", "description", "language", "topics", "stargazers_count", "fork"}
    assert calls[1].url.params["per_page"] == "30"
    assert calls[1].url.params["sort"] == "pushed"
    assert calls[0].headers["accept"] == "application/vnd.github+json"
    assert calls[0].headers["user-agent"] == "conferge-w07"
    assert calls[0].headers["authorization"] == f"Bearer {TOKEN}"


@pytest.mark.asyncio
async def test_fetch_user_hash_is_stable():
    calls: list[httpx.Request] = []
    async with GitHubEnricher(client=_client(_ok_handler(calls)), token="") as gh:
        a = await gh.fetch_user("avery-example")
        b = await gh.fetch_user("avery-example")
    assert a.content_hash == b.content_hash
    assert "authorization" not in calls[0].headers


@pytest.mark.asyncio
async def test_fetch_user_404_no_token_leak():
    async with GitHubEnricher(client=_client(lambda r: httpx.Response(404)), token=TOKEN) as gh:
        with pytest.raises(EnrichmentError) as exc:
            await gh.fetch_user("avery-example")
    assert str(exc.value) == "github: user not found"
    assert TOKEN not in str(exc.value) and TOKEN not in repr(exc.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [
    httpx.Response(403, headers={"X-RateLimit-Remaining": "0"}, json={"message": TOKEN}),
    httpx.Response(429, json={"message": "slow down"}),
])
async def test_fetch_user_rate_limited_no_token_leak(response):
    async with GitHubEnricher(client=_client(lambda r: response), token=TOKEN) as gh:
        with pytest.raises(EnrichmentError) as exc:
            await gh.fetch_user("avery-example")
    assert str(exc.value) == "github: rate_limited"
    assert TOKEN not in str(exc.value)


@pytest.mark.asyncio
async def test_fetch_user_network_error_no_token_leak():
    def boom(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"failed with {req.headers.get('authorization')}")

    async with GitHubEnricher(client=_client(boom), token=TOKEN) as gh:
        with pytest.raises(EnrichmentError) as exc:
            await gh.fetch_user("avery-example")
    assert str(exc.value) == "github: network error"
    assert exc.value.__cause__ is None
    assert TOKEN not in str(exc.value)


@pytest.mark.asyncio
async def test_fetch_user_invalid_login_makes_no_request():
    calls: list[httpx.Request] = []
    async with GitHubEnricher(client=_client(_ok_handler(calls))) as gh:
        with pytest.raises(EnrichmentError):
            await gh.fetch_user("orgs")
    assert calls == []


def test_apply_github_name_match_fills_fields_and_topics():
    profile, applied, reason = apply_github(_profile(), _record())
    assert applied and reason == "name match"
    p = profile.person
    assert str(p.github_url) == "https://github.com/avery-example"
    assert "mcp" in p.topics and "ai agents" in p.topics
    assert p.roles == []
    ev = p.evidence[-1]
    assert ev.provider == "github:api" and ev.source_record_id == "github:avery-example"
    assert ev.confidence == 0.8 and ev.source_mode == "live"


def test_apply_github_name_mismatch_not_applied():
    original = _profile(name="Blair Sample")
    profile, applied, reason = apply_github(original, _record())
    assert not applied and "name" in reason
    assert profile == original


def test_apply_github_different_declared_login_not_applied():
    original = _profile(github_url="https://github.com/someone-else")
    profile, applied, _ = apply_github(original, _record())
    assert not applied and profile == original


def test_apply_github_source_declared_and_no_overwrite():
    user = {"login": "avery-example", "name": "A. E.", "bio": "Building agents with MCP",
            "html_url": "https://github.com/avery-example"}
    original = _profile(name="Avery Example", bio="Existing bio", topics=["copilot"],
                        github_url="https://github.com/Avery-Example")
    profile, applied, reason = apply_github(original, _record(user=user, repos=[]))
    assert applied and reason == "source-declared github_url"
    p = profile.person
    assert p.bio == "Existing bio"
    assert str(p.github_url) == "https://github.com/Avery-Example"
    assert p.topics[0] == "copilot" and "mcp" in p.topics
    assert len(p.topics) == len(set(p.topics))
    assert p.evidence[-1].confidence == 1.0


def test_apply_github_topics_from_repo_topics_and_bio_fill():
    user = {"login": "avery-example", "name": "Avery Example", "bio": "Open source maintainer",
            "html_url": "https://github.com/avery-example"}
    repos = [{"name": "scanner", "description": None, "language": "Rust",
              "topics": ["secret scanning", "kubernetes"], "stargazers_count": 1,
              "fork": False}]
    profile, applied, _ = apply_github(_profile(), _record(user=user, repos=repos))
    assert applied
    assert profile.person.bio == "Open source maintainer"
    assert {"devsecops", "infra", "open source"} <= set(profile.person.topics)


@pytest.mark.asyncio
async def test_enrich_topics_keywords_and_roles():
    prof = _profile(title="Co-founder and CTO", bio="Agentic developer tools")
    prof = prof.model_copy(update={"talk_titles": ["Shipping MCP servers"]})
    out = await enrich_topics(prof)
    assert out.person.topics == ["ai agents", "developer tools", "mcp"]
    assert out.person.roles == ["founder", "executive"]


@pytest.mark.asyncio
async def test_enrich_topics_keeps_existing_roles():
    prof = _profile(title="Founder", roles=["investor"], topics=["llm"], bio="copilot")
    out = await enrich_topics(prof)
    assert out.person.roles == ["investor"]
    assert out.person.topics == ["llm", "copilot"]


class FailingExtractor:
    async def extract(self, texts: list[str]) -> list[str]:
        raise RuntimeError("llm down")


class FakeExtractor:
    async def extract(self, texts: list[str]) -> list[str]:
        return ["Copilot", "underwater basket weaving", "quantum gastronomy"]


@pytest.mark.asyncio
async def test_enrich_topics_failing_extractor_falls_back():
    out = await enrich_topics(_profile(bio="MCP and agents"), FailingExtractor())
    assert out.person.topics == ["ai agents", "mcp"]


@pytest.mark.asyncio
async def test_enrich_topics_fake_extractor_clipped_to_taxonomy():
    out = await enrich_topics(_profile(bio="MCP"), FakeExtractor())
    assert out.person.topics == ["mcp", "copilot"]


@pytest.mark.parametrize("name,cats,text,expected", [
    ("Example Ventures", [], None, None),  # "venture" alone is not enough
    ("Example Venture Partners", [], None, True),
    ("Example Capital", [], None, True),
    ("Example Labs", ["vc"], None, True),
    ("Example Labs", [], "Example Labs is a seed-stage VC fund", True),
    ("Adventure Example", [], None, None),
    ("Capitalize Example", [], None, None),
    ("Example Labs", [], "builds developer tools", None),
])
def test_investor_flag(name, cats, text, expected):
    company = Company(id="company:x", name=name, categories=cats)
    out = investor_flag(company, text)
    assert out.is_investor is expected
    if expected:
        assert "investor_heuristic" in out.categories
    else:
        assert out.categories == cats


def test_investor_flag_never_overwrites():
    company = Company(id="company:x", name="Example Ventures", is_investor=False)
    assert investor_flag(company, None).is_investor is False
