"""Offline tests for conferge.people.crunchbase: a real local HTTP server stands in for
api.brightdata.com (no Bright Data or crunchbase.com call)."""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from conferge.core.brightdata import BrightDataClient
from conferge.core.schemas import Company, Person
from conferge.core.store import GraphStore
from conferge.integration.memgraph import MemoryGraph, QueryResult
from conferge.people import crunchbase as cb


class FakeBrightData:
    """127.0.0.1 server: /request answers SERP JSON, /datasets/v3/* a trigger + poll flow."""

    def __init__(self, serp: dict | None = None, rows: list | None = None,
                 running_polls: int = 1) -> None:
        self.serp = serp or {"organic": []}
        self.rows = rows or []
        self.running_polls = running_polls
        self.requests: list[tuple[str, str, object]] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def _answer(self) -> None:
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length)) if length else None
                outer.requests.append((self.command, self.path, body))
                path = urlparse(self.path).path
                if path == "/request":
                    out = outer.serp
                elif path == "/datasets/v3/trigger":
                    out = {"snapshot_id": "sd_test1"}
                elif path.startswith("/datasets/v3/progress/"):
                    if outer.running_polls > 0:
                        outer.running_polls -= 1
                        out = {"status": "running", "snapshot_id": "sd_test1"}
                    else:
                        out = {"status": "ready", "snapshot_id": "sd_test1", "records": 2}
                elif path.startswith("/datasets/v3/snapshot/"):
                    out = outer.rows
                else:
                    out = {"error": "unknown"}
                data = json.dumps(out).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            do_GET = do_POST = _answer  # noqa: N815

            def log_message(self, *_: object) -> None:
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def client(self) -> BrightDataClient:
        return BrightDataClient("test-key", serp_zone="serp_z",
                                client=httpx.AsyncClient(base_url=self.url, timeout=5.0))

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture()
def fake():
    servers: list[FakeBrightData] = []

    def make(**kw) -> FakeBrightData:
        servers.append(FakeBrightData(**kw))
        return servers[-1]

    yield make
    for s in servers:
        s.close()


async def _no_sleep(_: float) -> None:
    return None


def _org(url: str, title: str = "x") -> dict:
    return {"link": url, "title": title}


# -- SERP lookup ---------------------------------------------------------------------------

async def test_one_clear_candidate_and_brd_json(fake) -> None:
    server = fake(serp={"organic": [
        _org("https://www.crunchbase.com/organization/example-labs"),
        _org("https://www.crunchbase.com/organization/example-labs/company_financials"),
        _org("https://www.linkedin.com/company/example-labs"),
    ]})
    async with server.client() as client:
        url = await cb.find_crunchbase_url(client, "Example Labs")
    assert url == "https://www.crunchbase.com/organization/example-labs"
    method, path, body = server.requests[0]
    assert (method, path) == ("POST", "/request")
    assert body["zone"] == "serp_z" and body["format"] == "raw"
    query = parse_qs(urlparse(body["url"]).query)
    assert query["brd_json"] == ["1"]
    assert query["q"] == ['"Example Labs" site:crunchbase.com/organization']


async def test_exact_slug_wins_among_several(fake) -> None:
    server = fake(serp={"organic": [
        _org("https://www.crunchbase.com/organization/acme-robotics"),
        _org("https://www.crunchbase.com/organization/acme"),
    ]})
    async with server.client() as client:
        assert await cb.find_crunchbase_url(client, "Acme") == (
            "https://www.crunchbase.com/organization/acme")


async def test_ambiguous_returns_none(fake) -> None:
    server = fake(serp={"organic": [
        _org("https://www.crunchbase.com/organization/nova-ai"),
        _org("https://www.crunchbase.com/organization/nova-labs"),
    ]})
    async with server.client() as client:
        assert await cb.find_crunchbase_url(client, "Nova") is None


async def test_no_candidate_returns_none(fake) -> None:
    server = fake(serp={"organic": [_org("https://www.crunchbase.com/person/jane-doe"),
                                    _org("https://example.com/organization/nova")]})
    async with server.client() as client:
        assert await cb.find_crunchbase_url(client, "Nova") is None


def test_parse_serp_html_fallback() -> None:
    page = ('<a href="/url?q=https://www.crunchbase.com/organization/foo-bar%3Fx&amp;sa=U">'
            '<h3>Foo</h3></a><script>"https://www.crunchbase.com/organization/hidden"</script>')
    assert cb.parse_serp(page) == ["https://www.crunchbase.com/organization/foo-bar"]


# -- dataset ----------------------------------------------------------------------------

async def test_trigger_and_poll_returns_rows(fake, monkeypatch) -> None:
    monkeypatch.setenv("BRIGHTDATA_CRUNCHBASE_DATASET", "gd_custom")
    rows = [{"name": "Example Labs", "url": "https://www.crunchbase.com/organization/example-labs"},
            {"error": "dead_page", "input": {"url": "https://www.crunchbase.com/organization/x"}}]
    server = fake(rows=rows, running_polls=2)
    progress: dict = {}
    async with server.client() as client:
        got, snapshot = await cb.fetch_company(
            client, ["https://www.crunchbase.com/organization/example-labs",
                     "https://www.crunchbase.com/organization/x"],
            poll=0, sleep=_no_sleep, progress_out=progress)
    assert snapshot == "sd_test1" and got == rows
    assert progress["status"] == "ready"
    trigger = next(r for r in server.requests if r[1].startswith("/datasets/v3/trigger"))
    assert "dataset_id=gd_custom" in trigger[1]
    assert trigger[2] == [{"url": "https://www.crunchbase.com/organization/example-labs"},
                          {"url": "https://www.crunchbase.com/organization/x"}]
    polls = [r for r in server.requests if r[1].startswith("/datasets/v3/progress/")]
    assert len(polls) == 3


async def test_poll_timeout_is_visible(fake) -> None:
    server = fake(running_polls=100)
    async with server.client() as client:
        with pytest.raises(cb.CrunchbaseUnavailable, match="not ready"):
            await cb.fetch_company(client, ["https://www.crunchbase.com/organization/a"],
                                   max_wait=30, poll=10, sleep=_no_sleep)


async def test_more_than_ten_urls_refused(fake) -> None:
    server = fake()
    async with server.client() as client:
        with pytest.raises(ValueError):
            await cb.fetch_company(client, [f"https://www.crunchbase.com/organization/{i}"
                                            for i in range(11)])
    assert server.requests == []


def test_dataset_id_default(monkeypatch) -> None:
    monkeypatch.delenv("BRIGHTDATA_CRUNCHBASE_DATASET", raising=False)
    assert cb.dataset_id() == "gd_l1vijqt9jfj7olije"


# -- normalize ----------------------------------------------------------------------------

@pytest.mark.parametrize(("value", "expected"), [
    ("$12.5M", "12500000"), ("US$1.2B", "1200000000"), ("$750K", "750000"),
    ("12,500,000", "12500000"), (3_000_000, "3000000"), (12.5, "12.5"),
    ({"value": 5000000, "currency": "USD"}, "5000000"),
    ({"value": 5000000, "currency": "EUR"}, None),
    ({"value": 5000000, "currency": "EUR", "value_usd": 5400000}, "5400000"),
    ("€12M", None), ("CA$5M", None), ("undisclosed", None), ("", None), (None, None),
    (True, None), (-5, None),
])
def test_parse_money_usd(value, expected) -> None:
    assert cb.parse_money_usd(value) == expected


def test_normalize_full_row() -> None:
    row = {
        "name": "Example Labs",
        "funding_rounds": {"last_funding_at": "2025-03-04T00:00:00Z",
                           "last_funding_type": "series_b", "num_funding_rounds": 3,
                           "value": {"value": 42000000, "currency": "USD",
                                     "value_usd": 42000000}},
        "investors": [{"value": "Seed Fund One"}, {"name": "Angel Two"}, "Seed Fund One"],
        "funding_rounds_list": [{"announced_on": "2024-01-01",
                                 "lead_investors": [{"value": "Lead VC"}]}],
        "num_employees": "c_00051_00100",
        "founded_date": {"value": "2019-01-01", "precision": "year"},
    }
    assert cb.normalize(row) == {
        "total_funding_usd": "42000000", "last_round_type": "series_b",
        "last_round_date": "2025-03-04", "investors": ["Seed Fund One", "Angel Two", "Lead VC"],
        "employee_range": "51-100", "founded": "2019",
    }


def test_normalize_never_invents() -> None:
    assert cb.normalize({"name": "Empty Co"}) == {
        "total_funding_usd": None, "last_round_type": None, "last_round_date": None,
        "investors": [], "employee_range": None, "founded": None,
    }
    out = cb.normalize({"funds_total": "€3M", "last_funding_at": "Q3 2024",
                        "founded_date": "sometime", "num_employees": ""})
    assert out["total_funding_usd"] is None and out["last_round_date"] is None
    assert out["founded"] is None and out["employee_range"] is None


def test_normalize_alt_keys_and_latest_round() -> None:
    out = cb.normalize({
        "total_funding_amount": "$8M", "founded_on": "May 2, 2018", "num_employees": "11-50",
        "funding_rounds_list": [
            {"announced_on": "2022-06-01", "investment_type": "seed"},
            {"announced_on": "Jan 15, 2024", "investment_type": "series_a",
             "investors": ["Fund A, Fund B"]},
        ],
    })
    assert out["total_funding_usd"] == "8000000"
    assert out["last_round_type"] == "series_a" and out["last_round_date"] == "2024-01-15"
    assert out["investors"] == ["Fund A", "Fund B"]
    assert out["founded"] == "2018-05-02" and out["employee_range"] == "11-50"


def test_is_investor() -> None:
    assert cb.is_investor({"name": "Seed Fund", "investor_type": ["venture_capital"]}, "Seed Fund")
    assert cb.is_investor({"name": "Seed Fund", "num_investments": "12"}, "Seed Fund")
    assert cb.is_investor({"type": "Investor"}, "Anything")
    assert cb.is_investor({"organization_types": ["company", "investor"]})
    assert not cb.is_investor({"name": "Tool Co", "num_investments": 0}, "Tool Co")
    assert not cb.is_investor({"name": "Tool Co", "company_type": "for_profit"}, "Tool Co")
    assert not cb.is_investor({"name": "Other Fund", "investor_type": ["vc"]}, "Seed Fund")
    assert not cb.is_investor({"error": "dead_page", "investor_type": ["vc"]})


# -- graph write --------------------------------------------------------------------------

class ReadableMemoryGraph(MemoryGraph):
    """MemoryGraph that also answers the one read write_company issues."""

    def query(self, q, params=None):  # type: ignore[no-untyped-def]
        if q == "MATCH (n:Company {id: $id}) RETURN properties(n)":
            props = self.nodes.get(("Company", str((params or {})["id"])))
            return QueryResult([[dict(props)]] if props is not None else [])
        return super().query(q, params)


NOW = datetime(2026, 10, 24, 12, tzinfo=timezone.utc)


def test_graph_write_keeps_non_null_fields() -> None:
    graph = ReadableMemoryGraph()
    store = GraphStore(graph)
    store.merge_node("Company", "co-1", {
        "name": "Example Labs", "is_investor": True, "crunchbase_url": "https://keep.example",
        "funding": json.dumps({"total_funding_usd": "1000", "last_round_type": None}),
    })
    funding = {"total_funding_usd": "9999", "last_round_type": "seed", "last_round_date": None,
               "investors": ["A"], "employee_range": None, "founded": "2020"}
    written = cb.write_company(store, "co-1", funding,
                               crunchbase_url="https://www.crunchbase.com/organization/x",
                               snapshot_id="sd_1", collected_at=NOW, investor=False)
    node = graph.nodes[("Company", "co-1")]
    stored = json.loads(node["funding"])
    assert stored["total_funding_usd"] == "1000"  # existing non-null kept
    assert stored["last_round_type"] == "seed" and stored["founded"] == "2020"
    assert stored["investors"] == ["A"] and "last_round_date" not in stored
    assert node["is_investor"] is True and "is_investor" not in written  # never False over True
    assert node["crunchbase_url"] == "https://keep.example"
    assert node["crunchbase_provider"] == "brightdata:crunchbase"
    assert node["crunchbase_snapshot_id"] == "sd_1"
    assert node["crunchbase_collected_at"].startswith("2026-10-24T12:00:00")
    assert node["name"] == "Example Labs" and not graph.refused


def test_graph_write_without_read_writes_only_non_none() -> None:
    graph = MemoryGraph()  # refuses reads: write_company falls back to non-None values only
    store = GraphStore(graph)
    cb.write_company(store, "co-2", {"total_funding_usd": None, "investors": []},
                     crunchbase_url=None, snapshot_id="sd_2", collected_at=NOW, investor=True)
    node = graph.nodes[("Company", "co-2")]
    assert node == {"is_investor": True}


# -- selection ----------------------------------------------------------------------------

def _person(pid: str, company: str | None, participation: str = "confirmed_speaker") -> Person:
    return Person(id=pid, name=pid, company_id=company, participation=participation)


def test_select_companies_top_speakers() -> None:
    companies = [Company(id=f"c{i}", name=n) for i, n in enumerate(
        ["Zeta", "Alpha", "Beta", "Gamma", "Delta", "Eps", "Eta", "Theta", "Iota", "Kappa",
         "Lambda", "Mu"])]
    people = [_person("p0", "c0"), _person("p1", "c0"), _person("p2", "c1"),
              _person("p3", "c2"), _person("host", "c3", "confirmed_organizer"),
              _person("p4", None), _person("p5", "unknown-co")]
    people += [_person(f"q{i}", f"c{i}") for i in range(4, 12)]
    ranked = ["p0", "host", "p1", "p2", "p3", "p4", "p5", *[f"q{i}" for i in range(4, 12)]]
    out = cb.select_companies(ranked, people, companies)
    assert [c.id for c in out][:1] == ["c0"]  # two top speakers
    assert len(out) == 10 and "c3" not in {c.id for c in out}  # hosts are not speakers
    names = [c.name for c in out[1:]]
    assert names == sorted(names, key=str.casefold)  # ties by name
    # only the top N speakers count
    assert [c.id for c in cb.select_companies(ranked, people, companies, top_speakers=2)] == ["c0"]


# -- caches -------------------------------------------------------------------------------

def test_public_cache_roundtrip(tmp_path) -> None:
    company = Company(id="co-1", name="Example Labs")
    url = "https://www.crunchbase.com/organization/example-labs"
    funding = cb.normalize({"funds_total": "$2M", "last_funding_type": "seed",
                            "last_funding_at": "2025-01-02"})
    entry = cb.public_entry(company, url, funding, snapshot_id="sd_1", collected_at=NOW)
    path = cb.write_public_cache([{**entry, "about": "private-ish raw"}], tmp_path / "pub.json")
    loaded = cb.load_public_cache(path)
    assert set(loaded) == {"co-1"} and "about" not in loaded["co-1"]
    assert loaded["co-1"]["funding"]["total_funding_usd"] == "2000000"
    view = cb.company_view(loaded["co-1"])
    assert view["last_round"] == {"type": "seed", "label": "Seed", "date": "2025-01-02"}
    assert view["evidence"] == {"provider": "brightdata:crunchbase", "source_mode": "cached",
                                "source_url": url, "collected_at": NOW.isoformat(),
                                "raw_ref": "sd_1"}
    assert cb.load_public_cache(tmp_path / "absent.json") == {}


def test_write_raw(tmp_path) -> None:
    path = cb.write_raw([{"name": "X"}], snapshot_id="sd_1", collected_at=NOW,
                        directory=tmp_path)
    assert path.name == "crunchbase_2026-10-24.json"
    assert json.loads(path.read_text())["records"] == [{"name": "X"}]


def test_lone_candidate_must_agree_with_the_company_name() -> None:
    from conferge.people.crunchbase import pick_candidate

    base = "https://www.crunchbase.com/organization/"
    assert pick_candidate("Momentic", [base + "momentic-ai"]) == base + "momentic-ai"
    assert pick_candidate("GitHub", [base + "github"]) == base + "github"
    assert pick_candidate("Overmind", [base + "acme-robotics"]) is None
    assert pick_candidate("Acme", [base + "acme-labs", base + "acme-ai"]) is None
    assert pick_candidate("Acme", [base + "acme", base + "acme-ai"]) == base + "acme"
