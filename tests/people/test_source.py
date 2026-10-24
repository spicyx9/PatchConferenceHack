import json

import httpx
import pytest

from conferge.core.brightdata import BrightDataClient
from conferge.core.contracts import Source
from conferge.core.schemas import DiscoveryQuery, SourceRef
from conferge.people.source import PeopleSource


def _query(candidates, limit=50):
    return DiscoveryQuery(domain="people", limit=limit, filters={"candidates": candidates})


def _serp(req: httpx.Request) -> httpx.Response:
    url = json.loads(req.content)["url"]
    if "Avery" in url:
        organic = [{"link": "https://www.linkedin.com/in/avery-example/",
                    "title": "Avery Example - CTO - Example Labs | LinkedIn",
                    "description": "San Francisco Bay Area"}]
    else:
        organic = []
    return httpx.Response(200, json={"organic": organic})


def test_is_source():
    assert isinstance(PeopleSource(client=BrightDataClient(None)), Source)


async def test_discover_without_key_fails_with_no_items():
    http = httpx.AsyncClient(base_url="https://api.brightdata.com",
                             transport=httpx.MockTransport(lambda r: httpx.Response(500)))
    async with http:
        src = PeopleSource(client=BrightDataClient(api_key=None, serp_zone=None, client=http))
        res = await src.discover(_query([{"name": "Avery Example", "company": "Example Labs"}]))
    assert res.items == []
    assert res.run_report.status == "failed"
    assert res.run_report.termination == "error"
    assert res.run_report.errors[0].startswith("missing_credentials:")


async def test_discover_no_candidates_fails():
    src = PeopleSource(client=BrightDataClient(api_key="k", serp_zone="z"))
    res = await src.discover(_query([]))
    assert res.run_report.status == "failed" and res.errors == ["no candidates supplied"]
    await src.client._client.aclose()


async def test_discover_ok_records():
    http = httpx.AsyncClient(base_url="https://api.brightdata.com",
                             transport=httpx.MockTransport(_serp))
    async with http:
        src = PeopleSource(client=BrightDataClient(api_key="k", serp_zone="z", client=http))
        res = await src.discover(_query([{"name": "Avery Example", "company": "Example Labs"}]))
    assert res.run_report.status == "ok" and res.run_report.termination == "exhausted"
    assert res.run_report.fetched_count == res.run_report.unique_count == 1
    rec = res.items[0]
    assert rec.provider == "brightdata:serp:linkedin"
    assert rec.source_id == "avery example|example labs"
    assert rec.source_mode == "live"
    assert str(rec.source_url) == "https://www.linkedin.com/in/avery-example/"
    assert rec.payload["status"] == "ok" and rec.payload["confidence"] == 1.0


async def test_discover_mixed_is_degraded_and_capped():
    http = httpx.AsyncClient(base_url="https://api.brightdata.com",
                             transport=httpx.MockTransport(_serp))
    async with http:
        src = PeopleSource(client=BrightDataClient(api_key="k", serp_zone="z", client=http))
        res = await src.discover(_query([
            {"name": "Avery Example", "company": "Example Labs"},
            {"name": "Blake Sample", "company": None},
            {"name": "Casey Placeholder"},
        ], limit=2))
    assert res.run_report.status == "degraded"
    assert len(res.items) == 2
    assert res.items[1].source_url is None
    assert any("capped" in w for w in res.run_report.warnings)


async def test_discover_rejects_other_domain():
    src = PeopleSource(client=BrightDataClient(None))
    with pytest.raises(ValueError):
        await src.discover(DiscoveryQuery(domain="events"))


async def test_fetch_details(monkeypatch):
    monkeypatch.setenv("BRIGHTDATA_LINKEDIN_PROFILE_DATASET", "ds")
    http = httpx.AsyncClient(
        base_url="https://api.brightdata.com",
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json=[{"name": "Avery"}])),
    )
    async with http:
        src = PeopleSource(client=BrightDataClient(api_key="k", client=http))
        rec = await src.fetch_details(SourceRef(
            provider="brightdata:serp:linkedin", source_id="x",
            url="https://www.linkedin.com/in/avery-example?trk=1"))
        assert rec.source_id == "avery-example" and rec.payload == {"name": "Avery"}
        with pytest.raises(ValueError):
            await src.fetch_details(SourceRef(provider="p", source_id="x",
                                              url="https://www.linkedin.com/company/x"))
