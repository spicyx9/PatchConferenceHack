"""SERP LinkedIn discovery: JSON organic only, bounded retries, strict verdicts, one batch."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from conferge.core.schemas import Company, Person
from conferge.integration import people_linkedin as li
from conferge.integration import serp_linkedin as serp

JAY = Person(id="p-jay", name="Jay Parikh", title="Executive Vice President, CoreAI",
             company_id="company:microsoft", participation="confirmed_speaker")
CASSIDY = Person(id="p-cassidy", name="Cassidy Williams", title="Sr. Director, Developer Advocacy",
                 company_id="company:github", participation="confirmed_speaker")
COMPANIES = [Company(id="company:microsoft", name="Microsoft"),
             Company(id="company:github", name="GitHub")]


def _hit(slug: str, title: str, snippet: str = "", position: int = 1) -> dict[str, Any]:
    """Bright Data's own organic keys: description is the snippet, rank the position."""
    return {"title": title, "link": f"https://www.linkedin.com/in/{slug}/?utm_source=x#top",
            "description": snippet, "rank": position}


def _mock(handler) -> httpx.AsyncClient:  # type: ignore[no-untyped-def]
    return httpx.AsyncClient(base_url="https://api.brightdata.com",
                             transport=httpx.MockTransport(handler))


async def _no_sleep(_: float) -> None:
    return None


# -- query and SERP call ------------------------------------------------------------------

def test_one_json_query_per_person_on_the_serp_zone() -> None:
    sent: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        return httpx.Response(200, json={"organic": [_hit("jayparikh", "Jay Parikh - EVP CoreAI - Microsoft | LinkedIn")]})

    hits = asyncio.run(serp.serp_organic(serp.query_for("Jay Parikh", "Microsoft"),
                                         http=_mock(handler), api_key="k"))
    (body,) = sent
    url = urlparse(body["url"])
    assert body["zone"] == "serp_api1" and body["format"] == "raw"
    assert url.netloc == "www.google.com" and url.path == "/search"
    assert parse_qs(url.query) == {"q": ["site:linkedin.com/in Jay Parikh Microsoft"],
                                   "brd_json": ["1"], "gl": ["us"]}
    assert hits[0]["rank"] == 1


def test_html_is_never_parsed_and_counts_as_a_retry() -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(200, text="<html><a href='https://www.linkedin.com/in/x'>x</a></html>")

    with pytest.raises(RuntimeError, match="not JSON"):
        asyncio.run(serp.serp_organic("q", http=_mock(handler), api_key="k", sleep=_no_sleep))
    assert len(calls) == 3


def test_a_transient_non_json_answer_is_retried() -> None:
    answers = iter([httpx.Response(200, text="<html></html>"),
                    httpx.Response(200, json={"organic": [{"title": "t", "link": "l"}]})])
    hits = asyncio.run(serp.serp_organic("q", http=_mock(lambda r: next(answers)), api_key="k",
                                         sleep=_no_sleep))
    assert hits == [{"title": "t", "link": "l"}]


def test_429_and_5xx_retry_twice_with_quadratic_jitter() -> None:
    calls, slept = [], []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(503 if len(calls) < 3 else 429)

    async def sleep(s: float) -> None:
        slept.append(round(s * 1000))

    with pytest.raises(RuntimeError, match="HTTP 429"):
        asyncio.run(serp.serp_organic("q", http=_mock(handler), api_key="k", sleep=sleep,
                                      rand=lambda a, b: b))
    assert len(calls) == 1 + serp.SERP_RETRIES == 3
    assert slept == [320 * 1 + 260, 320 * 4 + 260]


def test_network_errors_retry_twice_with_linear_jitter() -> None:
    calls, slept = [], []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        raise httpx.ConnectTimeout("slow")

    async def sleep(s: float) -> None:
        slept.append(round(s * 1000))

    with pytest.raises(RuntimeError, match="network error"):
        asyncio.run(serp.serp_organic("q", http=_mock(handler), api_key="k", sleep=sleep,
                                      rand=lambda a, b: 0))
    assert len(calls) == 3 and slept == [250, 500]


def test_4xx_is_not_retried() -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(401)

    with pytest.raises(RuntimeError, match="HTTP 401"):
        asyncio.run(serp.serp_organic("q", http=_mock(handler), api_key="k", sleep=_no_sleep))
    assert len(calls) == 1


def test_timeout_is_20_seconds() -> None:
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.extensions["timeout"])
        return httpx.Response(200, json={"organic": []})

    asyncio.run(serp.serp_organic("q", http=_mock(handler), api_key="k"))
    assert seen[0]["read"] == 20.0 and seen[0]["connect"] == 20.0


# -- summary, URL, verdict ----------------------------------------------------------------

def test_free_summary_from_title_and_snippet() -> None:
    s = serp.summary({"title": "Jay Parikh - EVP, CoreAI - Microsoft | LinkedIn",
                      "snippet": "Experience: Microsoft · Location: Seattle, Washington · 500+"})
    assert s == {"name": "Jay Parikh", "headline": "EVP, CoreAI - Microsoft",
                 "location": "Seattle, Washington"}
    assert serp.summary({"title": "Jay Parikh | LinkedIn", "snippet": "Builds things · Seattle"}) \
        == {"name": "Jay Parikh", "headline": None, "location": "Seattle"}


def test_canonical_url_strips_tracking_and_fragment() -> None:
    assert serp.canonical_url(
        "https://fr.linkedin.com/in/Jay-Parikh/?utm_source=a&utm_medium=b&gclid=1&fbclid=2#x"
    ) == "https://www.linkedin.com/in/jay-parikh/"
    assert serp.canonical_url("https://www.linkedin.com/company/microsoft/") is None


def test_found_when_name_and_company_corroborate() -> None:
    d = serp.judge(JAY, "Microsoft", [
        _hit("jayparikh", "Jay Parikh - EVP CoreAI - Microsoft | LinkedIn", "Microsoft · Seattle")])
    assert d.status == "found" and d.linkedin_url == "https://www.linkedin.com/in/jayparikh/"
    assert d.score >= 0.7 and d.serp_headline == "EVP CoreAI - Microsoft" and d.position == 1


def test_title_corroborates_when_company_is_absent() -> None:
    d = serp.judge(CASSIDY, "GitHub", [_hit(
        "cassidoo", "Cassidy Williams - Sr. Director, Developer Advocacy | LinkedIn", "Chicago")])
    assert d.status == "found", d.reasons
    assert "+0.3 person's title in title or snippet" in d.reasons


def test_initials_are_ignored_in_the_name() -> None:
    d = serp.judge(JAY, "Microsoft", [_hit("jparikh", "J. Jay Parikh - Microsoft | LinkedIn")])
    assert d.status == "found"


@pytest.mark.parametrize(("hit", "why"), [
    (_hit("someone", "Jay Smith - Microsoft | LinkedIn"), "name"),
    (_hit("jayparikh", "Jay Parikh - Chef | LinkedIn", "Paris"), "corroborates"),
])
def test_no_url_without_name_and_corroboration(hit: dict[str, Any], why: str) -> None:
    d = serp.judge(JAY, "Microsoft", [hit])
    assert d.status == "not_found" and d.linkedin_url is None and why in d.reasons[-1]


def test_goto_links_and_duplicate_hosts_are_not_candidates() -> None:
    goto = {"title": "Jay Parikh - Microsoft", "rank": 1,
            "link": "https://www.google.com/goto?url=CAESYwHrOzAV", "description": "Microsoft"}
    dup = {**_hit("JayParikh", "Jay Parikh - Microsoft | LinkedIn", "Microsoft", 3),
           "link": "https://fr.linkedin.com/in/JayParikh"}
    d = serp.judge(JAY, "Microsoft", [goto, _hit("jayparikh", "Jay Parikh - Microsoft | LinkedIn",
                                                   "Microsoft", 2), dup])
    assert d.status == "found" and d.linkedin_url == "https://www.linkedin.com/in/jayparikh/"
    assert d.position == 2


def test_a_tie_is_broken_only_by_the_person_title() -> None:
    d = serp.judge(JAY, "Microsoft", [
        _hit("jayparikh", "Jay Parikh - Executive Vice President at Microsoft",
             "Executive Vice President at Microsoft · Location: San Francisco Bay Area", 1),
        _hit("jay-parikh-a3", "Jay parikh - Microsoft Power Platform Developer",
             "Microsoft Power Platform · Sydney", 2)])
    assert d.status == "found" and d.linkedin_url == "https://www.linkedin.com/in/jayparikh/"
    assert d.reasons[-1] == "tie broken: the person's title is on this hit only"
    assert d.serp_location == "San Francisco Bay Area"


def test_ambiguous_top_hits_give_no_url() -> None:
    d = serp.judge(JAY, "Microsoft", [
        _hit("jayparikh", "Jay Parikh - Microsoft | LinkedIn", position=1),
        _hit("jay-parikh-2", "Jay Parikh - Microsoft | LinkedIn", position=2)])
    assert d.status == "not_found" and "ambiguous" in d.reasons[-1]


def test_targets_are_speakers_without_url_capped() -> None:
    people = [Person(id=f"s{i}", name=f"S {i}", participation="confirmed_speaker",
                     linkedin_url="https://www.linkedin.com/in/x/" if i % 2 else None)
              for i in range(80)] + [Person(id="h", name="H")]
    got = serp.targets_without_url(people)
    assert len(got) == 30 and all(p.linkedin_url is None for p in got)
    assert "h" not in {p.id for p in got}


# -- dataset batch and mapping ------------------------------------------------------------

def test_one_trigger_then_snapshot_every_2s_private_rows_dropped() -> None:
    calls: list[tuple[str, str]] = []
    polls = {"n": 0}
    slept: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        if request.url.path == "/datasets/v3/trigger":
            assert request.url.params["dataset_id"] == "gd_l1viktl72bvl7bjuj0"
            assert request.url.params["include_errors"] == "true"
            assert json.loads(request.content) == [{"url": u} for u in urls]
            return httpx.Response(200, json={"snapshot_id": "sd_b"})
        polls["n"] += 1
        if polls["n"] < 3:
            return httpx.Response(202, json={"status": "running"})
        return httpx.Response(200, json=[
            {"input": {"url": urls[0]}, "name": "Jay Parikh", "position": "EVP CoreAI",
             "current_company": {"name": "Microsoft", "title": "EVP"}},
            {"input": {"url": urls[1]}, "warning_code": "dead_page", "warning": "private"}])

    async def sleep(s: float) -> None:
        slept.append(s)

    urls = ["https://www.linkedin.com/in/jayparikh/", "https://www.linkedin.com/in/hidden/"]
    out = asyncio.run(serp.collect_batch(urls, api_key="k", http=_mock(handler), sleep=sleep))
    assert calls.count(("POST", "/datasets/v3/trigger")) == 1
    assert calls.count(("GET", "/datasets/v3/snapshot/sd_b")) == 3 and slept == [2.0, 2.0]
    assert out.snapshot_id == "sd_b" and out.status == "degraded"
    profiles = [p for r in out.records if (p := li.profile_from_record(r))]
    assert [p.linkedin_url for p in profiles] == [urls[0]]  # the private row gives no profile


def test_batch_holds_at_most_50_urls() -> None:
    sent = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/trigger"):
            sent.append(len(json.loads(request.content)))
            return httpx.Response(200, json={"snapshot_id": "sd"})
        return httpx.Response(200, json=[])

    asyncio.run(serp.collect_batch([f"https://www.linkedin.com/in/p{i}/" for i in range(70)],
                                   api_key="k", http=_mock(handler), sleep=_no_sleep))
    assert sent == [50]


def test_headline_is_the_dataset_position_field() -> None:
    p = li.profile_from_record({"input": {"url": "https://www.linkedin.com/in/a/"}, "name": "A B",
                                "position": "Chairman and CEO at Microsoft", "headline": "ignored",
                                "current_company": {"name": "Microsoft", "title": "Chairman and CEO"}})
    assert (p.headline, p.headline_source, p.title) == (
        "Chairman and CEO at Microsoft", "dataset:position", "Chairman and CEO")
    none = li.profile_from_record({"input": {"url": "https://www.linkedin.com/in/a/"}, "name": "A B"})
    assert none.headline is None and none.headline_source is None


# -- writes -------------------------------------------------------------------------------

class Store:
    def __init__(self) -> None:
        self.nodes: list[tuple[str, str, dict[str, Any]]] = []
        self.edges: list[Any] = []

    def merge_node(self, kind: str, node_id: str, props: dict[str, Any]) -> None:
        self.nodes.append((kind, node_id, props))

    def merge_edge(self, *args: Any) -> None:
        self.edges.append(args)


def test_url_write_is_person_only_with_serp_evidence() -> None:
    d = serp.judge(JAY, "Microsoft", [_hit("jayparikh", "Jay Parikh - Microsoft | LinkedIn")])
    store = Store()
    assert serp.write_urls(store, [d]) == ["p-jay"]
    ((kind, pid, props),) = store.nodes
    assert (kind, pid) == ("Person", "p-jay") and store.edges == []
    assert props["linkedin_url"] == "https://www.linkedin.com/in/jayparikh/"
    assert props["linkedin_url_provider"] == "brightdata:serp" and props["serp_score"] >= 0.7
    assert not {"presence_confidence", "participation", "event_ids"} & set(props)
    (after,) = serp.apply_urls([JAY], [d])
    changed = {k for k, v in after.model_dump().items() if JAY.model_dump()[k] != v}
    assert changed == {"linkedin_url"}


def test_public_cache_merges_and_exposes_serp_urls(tmp_path: Path) -> None:
    path = tmp_path / "linkedin_public.json"
    path.write_text(json.dumps({"profiles": [
        {"name": "Old One", "linkedin_url": "https://www.linkedin.com/in/old/", "company": "X",
         "provider": "brightdata:linkedin"}]}))
    prof = li.LinkedInProfile(linkedin_url="https://www.linkedin.com/in/jayparikh/",
                              name="Jay Parikh", headline="EVP CoreAI", company="Microsoft",
                              headline_source="serp:title", person_id="p-jay",
                              url_provider="brightdata:serp")
    li.write_public([li.Enrichment("p-jay", prof, 1.0, "company:microsoft")], path, merge=True)
    pool = li.load_public(path)
    assert set(pool) == {"https://www.linkedin.com/in/old/", "https://www.linkedin.com/in/jayparikh/"}
    assert li.serp_urls(pool) == {"p-jay": "https://www.linkedin.com/in/jayparikh/"}
    saved = json.loads(path.read_text())["profiles"]
    assert all(set(e) <= set(li.PUBLIC_FIELDS) for e in saved)  # public fields only


def test_identity_and_works_at_only_never_attends() -> None:
    prof = li.LinkedInProfile(linkedin_url="https://www.linkedin.com/in/jayparikh/",
                              name="Jay Parikh", company="Microsoft", person_id="p-jay",
                              url_provider="brightdata:serp")
    jay = JAY.model_copy(update={"linkedin_url": "https://www.linkedin.com/in/jayparikh/"})
    enrichments, _ = li.match([jay], COMPANIES, [prof])

    class GraphStore(Store):
        graph = None

        def __init__(self) -> None:
            super().__init__()
            self.graph = self

        def query(self, q: str, params: dict[str, Any] | None = None) -> Any:
            rows = [["company:microsoft"]] if "Company {id" in q and "WORKS_AT" not in q else []
            return type("R", (), {"result_set": rows})()

    store = GraphStore()
    li.write(store, enrichments)
    assert enrichments[0].identity_confidence == 1.0
    assert {e[2] for e in store.edges} == {"WORKS_AT"}
    assert all("presence_confidence" not in props for *_, props in store.nodes)


def test_fresh_probe_profile_keeps_the_serp_fields_of_the_public_cache() -> None:
    url = "https://www.linkedin.com/in/philipholleran/"
    public = {url: li.LinkedInProfile(linkedin_url=url, name="Philip Holleran", headline="Technologist",
                                      headline_source="serp:title", person_id="p-ph",
                                      url_provider="brightdata:serp", source_mode="cached")}
    fresh = {url: li.LinkedInProfile(linkedin_url=url, name="Philip Holleran", company="GitHub",
                                     title="Field CTO", snapshot_id="sd_x", source_mode="cached")}
    merged = li.merge_pools(public, fresh)[url]
    assert (merged.headline, merged.headline_source, merged.person_id, merged.url_provider) == (
        "Technologist", "serp:title", "p-ph", "brightdata:serp")
    assert merged.title == "Field CTO" and merged.snapshot_id == "sd_x"  # fresh data kept
