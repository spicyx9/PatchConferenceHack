import json

import httpx
import pytest

from conferge.core.brightdata import BrightDataClient
from conferge.people.linkedin import (
    THRESHOLD,
    LinkedInDatasets,
    LinkedInUnavailable,
    build_query,
    canonical_profile_url,
    fetch_posts,
    fetch_profile,
    find_profile,
    parse_serp,
    score_candidate,
)

GOOGLE_HTML = """
<html><body>
<script>var x = "https://www.linkedin.com/in/should-not-appear";</script>
<div class="g"><a href="/url?q=https://www.linkedin.com/in/avery-example-123%3Fx&amp;sa=U&amp;ved=1">
<h3>Avery Example - Staff Engineer - Example Labs | LinkedIn</h3></a>
<div>San Francisco Bay Area. Building developer tools at Example Labs.</div></div>
<div class="g"><a href="https://fr.linkedin.com/in/avery-example-99?trk=public">
<h3>Avery Example - Designer - Other Corp | LinkedIn</h3></a>
<div>Paris, France.</div></div>
<div class="g"><a href="/url?q=https://www.linkedin.com/company/example-labs&amp;sa=U">
<h3>Example Labs | LinkedIn</h3></a></div>
<a href="/url?q=https://www.linkedin.com/in/avery-example-123/&amp;sa=U">dup</a>
</body></html>
"""


def _bd(handler) -> tuple[BrightDataClient, httpx.AsyncClient]:
    http = httpx.AsyncClient(
        base_url="https://api.brightdata.com", transport=httpx.MockTransport(handler)
    )
    return BrightDataClient(api_key="k", serp_zone="z", unlocker_zone=None, client=http), http


def _serp_json(*organic: dict) -> str:
    return json.dumps({"organic": list(organic)})


def test_build_query():
    assert build_query("Avery Example", "Example Labs") == (
        '"Avery Example" "Example Labs" site:linkedin.com/in'
    )
    assert build_query("Avery Example", None) == '"Avery Example" site:linkedin.com/in'


def test_canonical_profile_url():
    assert canonical_profile_url("https://FR.LinkedIn.com/in/avery-x/?trk=1#a") == (
        "https://www.linkedin.com/in/avery-x/"
    )
    assert canonical_profile_url("https://www.linkedin.com/company/example-labs") is None
    assert canonical_profile_url("https://evil.example/in/avery") is None


def test_parse_html_unwraps_dedupes_and_drops_non_profiles():
    hits = parse_serp(GOOGLE_HTML)
    urls = [h["url"] for h in hits]
    assert urls == [
        "https://www.linkedin.com/in/avery-example-123/",
        "https://www.linkedin.com/in/avery-example-99/",
    ]
    assert hits[0]["title"].startswith("Avery Example - Staff Engineer")
    assert "Example Labs" in hits[0]["snippet"]
    assert all("company" not in u for u in urls)


def test_parse_json():
    text = _serp_json(
        {"link": "https://www.linkedin.com/in/avery-example/", "title": "Avery Example",
         "description": "Example Labs"},
        {"link": "https://www.linkedin.com/company/example-labs", "title": "Example Labs"},
        {"link": "https://uk.linkedin.com/in/avery-example?x=1", "title": "dup"},
    )
    hits = parse_serp(text)
    assert hits == [{"url": "https://www.linkedin.com/in/avery-example/",
                     "title": "Avery Example", "snippet": "Example Labs"}]


def test_score_exact_name_and_company_passes():
    hit = {"url": "https://www.linkedin.com/in/avery-example-123/",
           "title": "Avery Example - Staff Engineer - Example Labs | LinkedIn",
           "snippet": "San Francisco Bay Area"}
    cand = score_candidate("Avery Example", "Example Labs", hit)
    assert cand.score == 1.0
    assert len([r for r in cand.reasons if r.startswith("+0.")]) == 4


def test_score_namesake_other_company_below_threshold():
    hit = {"url": "https://www.linkedin.com/in/avery-example-99/",
           "title": "Avery Example - Designer - Other Corp | LinkedIn",
           "snippet": "Paris, France."}
    cand = score_candidate("Avery Example", "Example Labs", hit)
    assert cand.score < THRESHOLD


def test_score_accent_folding():
    hit = {"url": "https://www.linkedin.com/in/zoe-exemple/", "title": "ZOE EXEMPLE | LinkedIn",
           "snippet": None}
    cand = score_candidate("Zoé Exemple", None, hit)
    assert cand.score == pytest.approx(0.6)


async def test_find_profile_picks_confident_match():
    def handler(req):
        assert json.loads(req.content)["zone"] == "z"
        return httpx.Response(200, text=GOOGLE_HTML)

    bd, http = _bd(handler)
    async with http:
        lookup = await find_profile(bd, "Avery Example", "Example Labs")
    assert lookup.status == "ok"
    assert str(lookup.linkedin_url) == "https://www.linkedin.com/in/avery-example-123/"
    assert lookup.confidence == 1.0
    assert lookup.source_mode == "live" and lookup.collected_at.tzinfo is not None


async def test_find_profile_without_company_never_attaches_url():
    text = _serp_json({"link": "https://www.linkedin.com/in/avery-example/",
                       "title": "Avery Example | LinkedIn", "description": "San Francisco"})
    bd, http = _bd(lambda req: httpx.Response(200, text=text))
    async with http:
        lookup = await find_profile(bd, "Avery Example", None)
    assert lookup.confidence == pytest.approx(0.7)
    assert lookup.linkedin_url is None and lookup.status == "degraded"
    assert "name-only" in (lookup.error or "")


async def test_find_profile_namesake_only_gives_no_url():
    text = _serp_json({"link": "https://www.linkedin.com/in/avery-example-99/",
                       "title": "Avery Example - Designer - Other Corp",
                       "description": "Paris"})
    bd, http = _bd(lambda req: httpx.Response(200, text=text))
    async with http:
        lookup = await find_profile(bd, "Avery Example", "Example Labs")
    assert lookup.linkedin_url is None
    assert lookup.status == "degraded"
    assert lookup.candidates


async def test_find_profile_ambiguous_gives_no_url():
    text = _serp_json(
        {"link": "https://www.linkedin.com/in/avery-example-1/",
         "title": "Avery Example - Example Labs", "description": "New York"},
        {"link": "https://www.linkedin.com/in/avery-example-2/",
         "title": "Avery Example - Example Labs", "description": "San Francisco"},
    )
    bd, http = _bd(lambda req: httpx.Response(200, text=text))
    async with http:
        lookup = await find_profile(bd, "Avery Example", "Example Labs")
    assert lookup.linkedin_url is None
    assert lookup.status == "degraded"
    assert "ambiguous" in (lookup.error or "")


async def test_find_profile_missing_key_fails_without_url():
    def handler(req):
        raise AssertionError("no network call expected")

    http = httpx.AsyncClient(base_url="https://api.brightdata.com",
                             transport=httpx.MockTransport(handler))
    async with http:
        bd = BrightDataClient(api_key=None, serp_zone=None, client=http)
        lookup = await find_profile(bd, "Avery Example", "Example Labs")
        bd2 = BrightDataClient(api_key=None, serp_zone="z", client=http)
        lookup2 = await find_profile(bd2, "Avery Example", "Example Labs")
    for lk in (lookup, lookup2):
        assert lk.status == "failed"
        assert lk.linkedin_url is None and not lk.candidates
        assert lk.error.startswith("missing_credentials:")


async def test_find_profile_http_error_is_failed_not_credentials():
    bd, http = _bd(lambda req: httpx.Response(403, json={"debug": "secret"}))
    async with http:
        lookup = await find_profile(bd, "Avery Example", "Example Labs")
    assert lookup.status == "failed" and lookup.linkedin_url is None
    assert "secret" not in lookup.error and not lookup.error.startswith("missing_credentials")


async def test_fetch_profile_202_then_snapshot_ready():
    calls = []

    def handler(req):
        calls.append(req)
        if req.url.path == "/datasets/v3/scrape":
            assert json.loads(req.content) == {
                "input": [{"url": "https://www.linkedin.com/in/avery-example-123/"}]
            }
            assert req.url.params["dataset_id"] == "ds-profile"
            return httpx.Response(202, json={"snapshot_id": "snap1"})
        if req.url.path == "/datasets/v3/snapshot/snap1":
            if sum(1 for c in calls if "snapshot" in c.url.path) == 1:
                return httpx.Response(202, json={"status": "running"})
            return httpx.Response(200, json=[{"name": "Avery Example", "city": "SF"}])
        raise AssertionError(req.url.path)

    sleeps = []

    async def fake_sleep(s):
        sleeps.append(s)

    bd, http = _bd(handler)
    async with http:
        rec = await fetch_profile(bd, "https://www.linkedin.com/in/avery-example-123/",
                                  dataset_id="ds-profile", sleep=fake_sleep)
    assert rec.provider == "brightdata:linkedin"
    assert rec.source_id == "avery-example-123"
    assert rec.request_id == "snap1"
    assert rec.payload == {"name": "Avery Example", "city": "SF"}
    assert rec.source_mode == "live"
    assert sleeps == [5.0, 5.0]


async def test_fetch_profile_times_out():
    def handler(req):
        if req.url.path == "/datasets/v3/scrape":
            return httpx.Response(202, json={"snapshot_id": "snap1"})
        return httpx.Response(202, json={"status": "running"})

    async def fake_sleep(_):
        return None

    bd, http = _bd(handler)
    async with http:
        with pytest.raises(LinkedInUnavailable, match="not ready"):
            await fetch_profile(bd, "https://www.linkedin.com/in/a/", dataset_id="d",
                                poll_interval=1.0, timeout_s=3.0, sleep=fake_sleep)


async def test_fetch_error_record_raises():
    bd, http = _bd(lambda req: httpx.Response(
        200, json=[{"error": "blocked secret body", "error_code": "dead_page"}]))
    async with http:
        with pytest.raises(LinkedInUnavailable) as err:
            await fetch_profile(bd, "https://www.linkedin.com/in/a/", dataset_id="d")
    assert "dead_page" in str(err.value) and "secret" not in str(err.value)


async def test_missing_dataset_id_raises(monkeypatch):
    monkeypatch.delenv("BRIGHTDATA_LINKEDIN_PROFILE_DATASET", raising=False)
    monkeypatch.delenv("BRIGHTDATA_LINKEDIN_POSTS_DATASET", raising=False)
    bd, http = _bd(lambda req: httpx.Response(500))
    async with http:
        # Profiles default to the documented dataset gd_l1viktl72bvl7bjuj0; posts have none.
        assert LinkedInDatasets.from_env().profile == "gd_l1viktl72bvl7bjuj0"
        with pytest.raises(LinkedInUnavailable, match="^missing_credentials:"):
            await fetch_posts(bd, "https://www.linkedin.com/in/a/")


async def test_fetch_posts_limits(monkeypatch):
    monkeypatch.setenv("BRIGHTDATA_LINKEDIN_POSTS_DATASET", "ds-posts")
    assert LinkedInDatasets.from_env().posts == "ds-posts"
    bd, http = _bd(lambda req: httpx.Response(200, json=[{"id": i} for i in range(5)]))
    async with http:
        rec = await fetch_posts(bd, "https://www.linkedin.com/in/a/", limit=2)
    assert rec.payload == {"posts": [{"id": 0}, {"id": 1}]}
