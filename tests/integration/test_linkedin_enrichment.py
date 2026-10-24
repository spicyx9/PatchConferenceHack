"""LinkedIn enrichment: one bounded Bright Data collection, identity only, never presence.

Offline tests mock Bright Data with httpx.MockTransport. The graph test needs FalkorDB
(FALKORDB_HOST / FALKORDB_PORT; skipped when it does not answer): it compares the top 5 of
people_for_goal with and without enrichment on the fixture graph.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx
import pytest

from conferge.core.schemas import Company, Person
from conferge.integration import people_linkedin as li

AT = datetime(2026, 10, 24, 19, 0, tzinfo=timezone.utc)
URL = "https://www.linkedin.com/in/{}/"


def _record(slug: str, name: str, company: str | None, **extra: Any) -> dict[str, Any]:
    rec = {"input": {"url": URL.format(slug)}, "name": name, "position": f"{name} headline",
           "current_company": {"name": company, "title": "Founder"} if company else None,
           "city": "San Francisco", "about": "Builds agents.", "followers": 1200}
    return {**rec, **extra}


def _collection(records: list[dict[str, Any]], kind: str = "collection",
                snapshot_id: str = "sd_test") -> li.Collection:
    return li.Collection(status="ok", collected_at=AT, inputs=[], records=records, kind=kind,
                         snapshot_id=snapshot_id)


def _profiles(records: list[dict[str, Any]]) -> list[li.LinkedInProfile]:
    return [p for r in records if (p := li.profile_from_record(
        r, snapshot_id="sd_test", collected_at=AT.isoformat()))]


# -- collection ---------------------------------------------------------------------------

def _mock(handler) -> httpx.AsyncClient:  # type: ignore[no-untyped-def]
    return httpx.AsyncClient(base_url="https://api.brightdata.com",
                             transport=httpx.MockTransport(handler))


def test_one_scrape_request_per_20_inputs_on_the_profile_dataset() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        body = json.loads(request.content)
        return httpx.Response(200, json=[{"input": i, "name": "x"} for i in body["input"]],
                              headers={"x-brd-cost": "0.03"})

    urls = [URL.format(f"p{i}") for i in range(25)]
    out = asyncio.run(li.collect(urls, http_client=_mock(handler), api_key="k"))
    assert [c.url.path for c in calls] == ["/datasets/v3/scrape"] * 2
    assert [len(json.loads(c.content)["input"]) for c in calls] == [20, 5]
    assert all(c.url.params["dataset_id"] == "gd_l1viktl72bvl7bjuj0" for c in calls)
    assert (out.status, len(out.records), out.requests, out.http_status) == ("ok", 25, 2, 200)
    assert out.cost == {"x-brd-cost": "0.03"}  # kept exactly as returned


def test_at_most_two_retries_then_a_visible_failure() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(503, json={"error": "busy"})

    out = asyncio.run(li.collect([URL.format("a")], http_client=_mock(handler), api_key="k"))
    assert len(calls) == 1 + li.RETRIES == 3
    assert out.status == "failed" and "HTTP 503" in out.errors[0] and out.records == []


def test_running_snapshot_is_read_back_never_resent(monkeypatch: pytest.MonkeyPatch) -> None:
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.url.path == "/datasets/v3/scrape":
            return httpx.Response(202, json={"snapshot_id": "sd_run"})
        return httpx.Response(200, json=[_record("a", "Avery Sample", None)])

    async def no_sleep(_: float) -> None:
        return None

    monkeypatch.setattr(li.asyncio, "sleep", no_sleep)
    out = asyncio.run(li.collect([URL.format("a")], http_client=_mock(handler), api_key="k"))
    assert paths.count("/datasets/v3/scrape") == 1
    assert out.snapshot_id == "sd_run" and out.status == "ok" and len(out.records) == 1


def test_without_key_nothing_is_sent() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no request without a key")

    out = asyncio.run(li.collect([URL.format("a")], http_client=_mock(handler), api_key=""))
    assert out.status == "failed" and "BRIGHTDATA_API_KEY" in out.errors[0]


def test_existing_snapshot_is_downloaded_not_recollected(tmp_path: Path) -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json=[_record("a", "Avery Sample", "AgentWorks")])

    out = asyncio.run(li.download_snapshot("sd_old", http_client=_mock(handler), api_key="k"))
    assert [(c.method, c.url.path, c.url.params["format"]) for c in calls] == [
        ("GET", "/datasets/v3/snapshot/sd_old", "json")]
    assert (out.kind, out.status, out.inputs) == ("snapshot", "ok", [URL.format("a")])
    assert li.save(out, tmp_path).name == "linkedin_sd_old.json"


def test_every_record_is_saved_and_pooled_snapshots_first(tmp_path: Path) -> None:
    old = _collection([_record("a", "Avery Sample", "From Snapshot")], "snapshot", "sd_old")
    new = _collection([_record("a", "Avery Sample", "From Collection"),
                       _record("b", "Blake Example", "B Co")])
    new.collected_at = AT + timedelta(minutes=5)
    li.save(old, tmp_path)
    path = li.save(new, tmp_path)
    assert path.name == "linkedin_20261024T190500Z.json"
    assert json.loads(path.read_text())["records"] == new.records  # as returned
    pool = li.load_pool(tmp_path, now=AT + timedelta(hours=1))
    assert pool[URL.format("a")].company == "From Snapshot"  # the snapshot wins
    assert pool[URL.format("a")].snapshot_id == "sd_old"
    assert {p.source_mode for p in pool.values()} == {"cached"}
    assert li.load_pool(tmp_path, now=AT + timedelta(hours=25)) == {}


def test_new_collection_only_when_more_than_three_targets_are_missing() -> None:
    targets = [Person(id=f"s{i}", name=f"S {i}", linkedin_url=URL.format(f"s{i}"))
               for i in range(10)]
    pool = {URL.format(f"s{i}"): li.LinkedInProfile(linkedin_url=URL.format(f"s{i}"))
            for i in range(7)}
    assert [t.id for t in li.missing(targets, pool)] == ["s7", "s8", "s9"]
    assert len(li.missing(targets, pool)) < li.NEW_COLLECTION_MIN_MISSING == 4
    assert len(li.profiles_for(targets, pool)) == 7


# -- mapping, targets, identity -----------------------------------------------------------

def test_profile_url_ignores_slug_case_and_locale_host() -> None:
    rec = {"url": "https://ro.linkedin.com/in/Michael-Fairchild-1", "name": "Michael Fairchild"}
    assert li.profile_from_record(rec).linkedin_url == URL.format("michael-fairchild-1")


def test_profile_keeps_the_documented_fields() -> None:
    p = li.profile_from_record(_record("avery", "Avery Sample", "AgentWorks"))
    assert p == li.LinkedInProfile(
        linkedin_url=URL.format("avery"), name="Avery Sample", headline="Avery Sample headline",
        title="Founder", company="AgentWorks", location="San Francisco", about="Builds agents.",
        followers=1200)
    assert li.profile_from_record({"error": "dead page", "input": {"url": URL.format("x")}}) is None


def test_targets_are_ranked_speakers_then_hosts_with_a_url() -> None:
    speakers = [Person(id=f"s{i}", name=f"S {i}", participation="confirmed_speaker",
                       linkedin_url=URL.format(f"s{i}") if i != 2 else None) for i in range(14)]
    hosts = [Person(id=f"h{i}", name=f"H {i}", linkedin_url=URL.format(f"h{i}")) for i in range(7)]
    ranked = [f"s{i}" for i in reversed(range(14))]
    got = li.select_targets(ranked, speakers, hosts)
    assert [p.id for p in got[:10]] == [f"s{i}" for i in (13, 12, 11, 10, 9, 8, 7, 6, 5, 4)]
    assert [p.id for p in got[10:]] == ["h0", "h1", "h2", "h3", "h4"]


def test_fixture_hosts_carry_no_linkedin_url_today() -> None:
    hosts = li.fixture_hosts()
    assert len(hosts) == 32 and not [h for h in hosts if h.linkedin_url]


@pytest.mark.parametrize(("name", "company", "expected"), [
    ("Avery Sample", "AgentWorks Inc.", 1.0),   # name + company
    ("Avery  SAMPLE", "Other Corp", 0.7),       # name only
    ("Ávery J. Sample", None, 0.7),             # accents, middle initial
    ("A. Avery Sample", None, 0.7),             # leading initial
    ("Avery S.", "AgentWorks", 0.42),           # abbreviated last name: unchanged
    ("Someone Else", "AgentWorks", 0.42),       # unchanged
])
def test_identity_confidence(name: str, company: str | None, expected: float) -> None:
    person = Person(id="p", name="Avery Sample", identity_confidence=0.42)
    profile = li.LinkedInProfile(linkedin_url=URL.format("a"), name=name, company=company)
    assert li.identity_confidence(person, "AgentWorks", profile) == expected


# -- writes: identity only, never presence ------------------------------------------------

class RecordingStore:
    """GraphStore stand-in: records the MERGE calls, answers the Company lookup."""

    def __init__(self, companies: set[str],
                 works_at: dict[tuple[str, str], dict[str, Any]] | None = None) -> None:
        self.companies = companies
        self.works_at = works_at or {}
        self.nodes: list[tuple[str, str, dict[str, Any]]] = []
        self.edges: list[tuple[str, str, str, str, str, dict[str, Any]]] = []
        self.graph = self

    def query(self, q: str, params: dict[str, Any] | None = None) -> Any:
        params = params or {}
        if "WORKS_AT" in q:
            edge = self.works_at.get((params["p"], params["c"]))
            rows = [[edge]] if edge is not None else []
        else:
            rows = [[params["id"]]] if params.get("id") in self.companies else []
        return type("R", (), {"result_set": rows})()

    def merge_node(self, kind: str, node_id: str, props: dict[str, Any]) -> None:
        self.nodes.append((kind, node_id, props))

    def merge_edge(self, fk: str, fid: str, rel: str, tk: str, tid: str,
                   props: dict[str, Any]) -> None:
        self.edges.append((fk, fid, rel, tk, tid, props))


PERSON_KEYS = {"identity_confidence", "headline", "company", "provider", "dataset_id",
               "snapshot_id", "linkedin_source_url", "linkedin_collected_at",
               "linkedin_source_mode"}
PEOPLE = [Person(id="p1", name="Avery Sample", company_id="company:agentworks",
                 participation="confirmed_speaker", linkedin_url=URL.format("avery"),
                 event_ids=["ev1"], presence_confidence=0.9),
          Person(id="p2", name="Blake Example", participation="confirmed_speaker",
                 linkedin_url=URL.format("blake"))]
COMPANIES = [Company(id="company:agentworks", name="AgentWorks")]


def test_writes_identity_headline_company_and_works_at_only() -> None:
    records = [_record("avery", "Avery Sample", "AgentWorks"),
               _record("blake", "Blake Example", "New Labs"),
               _record("blake-imposter", "Not Blake", "X")]
    enrichments, unmatched = li.match(PEOPLE, COMPANIES, _profiles(records))
    assert unmatched == [URL.format("blake-imposter")]
    store = RecordingStore({"company:agentworks"})
    report = li.write(store, enrichments)

    person_writes = [(nid, props) for kind, nid, props in store.nodes if kind == "Person"]
    assert [nid for nid, _ in person_writes] == ["p1", "p2"]
    for _, props in person_writes:
        assert set(props) <= PERSON_KEYS and "presence_confidence" not in props
        assert props["provider"] == "brightdata:linkedin" and props["snapshot_id"] == "sd_test"
    assert dict(person_writes)["p1"]["identity_confidence"] == 1.0
    assert dict(person_writes)["p2"]["identity_confidence"] == 0.7
    assert {e[2] for e in store.edges} == {"WORKS_AT"}
    assert not any(e[2].startswith("ATTENDS") or e[3] == "Event" for e in store.edges)
    assert report.companies_created == ["company:new-labs"]  # existing AgentWorks untouched
    assert report.works_at == [("p1", "company:agentworks"), ("p2", "company:new-labs")]


def test_linkedin_company_matching_the_known_one_reuses_its_id() -> None:
    people = [Person(id="p1", name="Avery Sample", company_id="co-fx-agentworks",
                     linkedin_url=URL.format("avery"))]
    companies = [Company(id="co-fx-agentworks", name="AgentWorks (fictional)")]
    (e,), _ = li.match(people, companies,
                       _profiles([_record("avery", "Avery Sample", "AgentWorks")]))
    assert e.company_id == "co-fx-agentworks" and e.identity_confidence == 1.0


ORIGINAL = {"source": "rainfocus:github-universe-2026", "verification": "person_record",
            "source_mode": "fixture", "observed_at": "2026-10-24T06:33:16+00:00",
            "confidence": 1.0, "title": "Sr. Director", "evidence_count": 1}


def test_existing_works_at_keeps_provenance_and_gets_linkedin_as_corroboration() -> None:
    enrichments, _ = li.match(PEOPLE, COMPANIES,
                              _profiles([_record("avery", "Avery Sample", "AgentWorks")]))
    store = RecordingStore({"company:agentworks"},
                           {("p1", "company:agentworks"): dict(ORIGINAL)})
    report = li.write(store, enrichments)
    (_, _, rel, _, _, props), = store.edges
    assert rel == "WORKS_AT" and report.works_at_corroborated == [("p1", "company:agentworks")]
    # Provenance is never written on an existing edge: only additions.
    assert not set(props) & {"source", "verification", "source_mode", "observed_at",
                             "confidence", "title", "provider"}
    assert props["evidence_sources"] == ["rainfocus:github-universe-2026", "brightdata:linkedin"]
    assert props["evidence_count"] == 2 and props["identity_confidence"] == 1.0
    assert props["linkedin_verification"] == "linkedin_profile"
    assert props["linkedin_snapshot_id"] == "sd_test"


def test_corroboration_is_idempotent_and_never_lowers_identity() -> None:
    enrichments, _ = li.match(PEOPLE, COMPANIES,
                              _profiles([_record("avery", "Avery Sample", "Other Corp")]))
    edge = {**ORIGINAL, "evidence_sources": [ORIGINAL["source"], "brightdata:linkedin"],
            "evidence_count": 2, "identity_confidence": 1.0, "snapshot_id": "sd_old"}
    e = enrichments[0]
    props = li._corroboration(edge, li.Enrichment(e.person_id, e.profile, 0.7, e.company_id))
    assert props["evidence_sources"] == edge["evidence_sources"] and "evidence_count" not in props
    assert "identity_confidence" not in props  # 0.7 never lowers 1.0
    assert props["snapshot_id"] is None  # the first version's edge key is removed


@pytest.mark.parametrize(("edge", "expected"), [
    # demo reload: ingest wrote evidence_count=1 back, evidence_sources kept LinkedIn
    ({**ORIGINAL, "evidence_sources": [ORIGINAL["source"], "brightdata:linkedin"]}, 2),
    # edge created by LinkedIn without a count (first version)
    ({"source": "brightdata:linkedin", "verification": "linkedin_profile",
      "evidence_sources": ["brightdata:linkedin"]}, 1),
])
def test_evidence_count_never_below_the_number_of_sources(edge: dict, expected: int) -> None:
    enrichments, _ = li.match(PEOPLE, COMPANIES,
                              _profiles([_record("avery", "Avery Sample", "AgentWorks")]))
    props = li._corroboration(edge, enrichments[0])
    assert props["evidence_count"] == expected
    assert "verification" not in props and "source" not in props


def test_in_memory_people_only_change_identity_confidence() -> None:
    enrichments, _ = li.match(PEOPLE, COMPANIES,
                              _profiles([_record("avery", "Avery Sample", "AgentWorks")]))
    after = li.apply_to_people(PEOPLE, enrichments)
    before, now = PEOPLE[0].model_dump(), after[0].model_dump()
    assert {k for k in before if before[k] != now[k]} == {"identity_confidence"}
    assert now["presence_confidence"] == 0.9 and now["event_ids"] == ["ev1"]
    assert after[1] == PEOPLE[1]


def test_people_card_shows_linkedin_evidence() -> None:
    from fastapi.testclient import TestClient

    from conferge.api.app import create_app
    from conferge.api.data import load_fixture
    from conferge.api.providers import Providers

    data = load_fixture()
    data.people = [p.model_copy(update={"linkedin_url": URL.format(p.id)}) for p in data.people]
    records = [_record(p.id, p.name, "AgentWorks") for p in data.people]
    enrichments, _ = li.match(data.people, data.companies, _profiles(records))
    data.linkedin = li.cards(enrichments)
    client = TestClient(create_app(data=data, found=Providers(), graph_probe=False))
    client.post("/api/v1/goal", json={"text": data.demo_goal_text, "user_id": "demo-user"})
    body = client.get("/api/v1/people?limit=5").json()
    card = next(c for c in body["items"] if c["person"])
    assert card["linkedin"]["provider"] == "brightdata:linkedin"
    assert card["linkedin"]["headline"] == f"{card['person']['name']} headline"
    assert card["linkedin"]["company"] == "AgentWorks" and card["linkedin"]["snapshot_id"] == "sd_test"
    assert card["linkedin"]["dataset_id"] == "gd_l1viktl72bvl7bjuj0"


# -- FalkorDB: top 5 with and without enrichment ------------------------------------------

GRAPH = "conferge_test_linkedin_enrichment"


def _rel_counts(store: Any) -> dict[str, int]:
    rows = store.graph.query("MATCH ()-[r]->() RETURN type(r), count(r)").result_set
    return {r[0]: r[1] for r in rows}


def test_graph_top5_before_after_and_no_presence_written(monkeypatch: pytest.MonkeyPatch) -> None:
    from conferge.api.data import load_fixture
    from conferge.api.logic import parse_goals
    from conferge.core.store import connect_graph, connect_graph_or_none
    from conferge.graph import GraphBundle, ingest_bundle
    from conferge.graph.queries import people_for_goal

    monkeypatch.setenv("FALKORDB_GRAPH", GRAPH)
    if connect_graph_or_none(timeout=0.5) is None:
        pytest.skip("FalkorDB not reachable (FALKORDB_HOST/FALKORDB_PORT)")
    store = connect_graph()
    try:
        store.graph.delete()
    except Exception:  # noqa: BLE001 - absent graph
        pass
    store = connect_graph()
    try:
        data = load_fixture()
        goals = parse_goals(data.demo_goal_text)
        ingest_bundle(store, GraphBundle(
            source_mode="fixture", conference=data.conference, companies=data.companies,
            people=data.people, events=data.events, goals=goals))
        goal = goals[0].id
        before = people_for_goal(store, "demo-user", goal, 5)["rows"]
        rels_before = _rel_counts(store)
        presence_before = store.graph.query(
            "MATCH (p:Person) RETURN p.id, p.presence_confidence ORDER BY p.id").result_set

        speakers = [p for p in data.people if p.participation == "confirmed_speaker"]
        people = [p.model_copy(update={"linkedin_url": URL.format(p.id)}) if p in speakers else p
                  for p in data.people]
        names = {c.id: c.name for c in data.companies}
        records = [_record(p.id, p.name, names.get(p.company_id or "") or "New Labs (fictional)")
                   for p in speakers]
        enrichments, unmatched = li.match(people, data.companies, _profiles(records))
        assert len(enrichments) == len(speakers) and not unmatched
        original = {(r[0], r[1]): r[2] for r in store.graph.query(
            "MATCH (p:Person)-[r:WORKS_AT]->(c:Company) RETURN p.id, c.id, properties(r)"
        ).result_set}
        report = li.write(store, enrichments)
        li.write(store, enrichments)  # a second run adds nothing
        after = people_for_goal(store, "demo-user", goal, 5)["rows"]

        print("top5 before:", [(r["person_id"], r["score"]) for r in before])
        print("top5 after: ", [(r["person_id"], r["score"]) for r in after])
        assert len(before) == len(after) == 5
        tagged = store.graph.query(
            "MATCH (p:Person {provider: 'brightdata:linkedin'}) RETURN p.id, p.identity_confidence,"
            " p.headline, p.snapshot_id").result_set
        assert tagged and {r[0] for r in tagged} == set(report.persons_written)
        assert all(r[1] in (1.0, 0.7) and r[2] and r[3] == "sd_test" for r in tagged)
        # Identity only: every relationship type keeps its count except WORKS_AT, and no
        # presence is written or changed.
        rels_after = _rel_counts(store)
        assert {k: v for k, v in rels_after.items() if k != "WORKS_AT"} == \
            {k: v for k, v in rels_before.items() if k != "WORKS_AT"}
        assert rels_after.get("ATTENDS_CONFIRMED", 0) == rels_before.get("ATTENDS_CONFIRMED", 0)
        assert report.works_at_corroborated, "fixture speakers carry a person_record WORKS_AT"
        for pid, cid in report.works_at_corroborated:
            now = store.graph.query(
                "MATCH (:Person {id: $p})-[r:WORKS_AT]->(:Company {id: $c}) RETURN properties(r)",
                params={"p": pid, "c": cid}).result_set[0][0]
            before_edge = original[(pid, cid)]
            for key in ("source", "verification", "source_mode", "observed_at", "confidence",
                        "title"):
                assert now.get(key) == before_edge.get(key), (pid, key)
            assert now["verification"] == "person_record"
            assert now["evidence_sources"] == [before_edge["source"], "brightdata:linkedin"]
            assert now["evidence_count"] == before_edge["evidence_count"] + 1
        assert store.graph.query(
            "MATCH (p:Person) RETURN p.id, p.presence_confidence ORDER BY p.id").result_set \
            == presence_before
    finally:
        store.graph.delete()
