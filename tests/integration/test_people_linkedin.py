from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from conferge.core import brightdata
from conferge.core.schemas import Person, SourceRecord
from conferge.integration.people_linkedin import enrich_with_linkedin

AT = datetime(2026, 10, 24, 18, 0, tzinfo=timezone.utc)
PEOPLE = [Person(id="p1", name="A", linkedin_url="https://www.linkedin.com/in/a/"),
          Person(id="p2", name="B", linkedin_url="https://www.linkedin.com/in/b/", bio="kept"),
          Person(id="p3", name="C")]


def test_enriches_only_people_with_a_linkedin_url(monkeypatch: pytest.MonkeyPatch) -> None:
    import conferge.people.linkedin as li

    monkeypatch.setattr(brightdata.BrightDataClient, "from_env", classmethod(lambda cls: cls("k")))

    async def fake(client, url, **kw):  # type: ignore[no-untyped-def]
        if url.endswith("/b/"):
            raise li.LinkedInUnavailable("snapshot failed")
        return SourceRecord(provider="brightdata:linkedin", source_id=url, source_mode="live",
                            collected_at=AT, payload={"about": "Builds agents."}, source_url=url)

    monkeypatch.setattr(li, "fetch_profile", fake)
    people, report = asyncio.run(enrich_with_linkedin(PEOPLE, limit=5))
    p1, p2, p3 = people
    assert p1.bio == "Builds agents." and p1.evidence[-1].provider == "brightdata:linkedin"
    assert p1.evidence[-1].collected_at == AT
    assert p2.bio == "kept" and p2.evidence == []  # failure leaves the person untouched
    assert p3 == PEOPLE[2]  # no URL: never fetched, never matched by name
    assert (report.status, report.fetched_count, report.unique_count) == ("degraded", 2, 1)
    assert "snapshot failed" in report.errors[0]


def test_without_key_reports_failed_and_changes_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(brightdata.BrightDataClient, "from_env", classmethod(lambda cls: cls(None)))
    people, report = asyncio.run(enrich_with_linkedin(PEOPLE))
    assert people == PEOPLE and report.status == "failed"
    assert report.errors == ["Bright Data key missing; set BRIGHTDATA_API_KEY"]
