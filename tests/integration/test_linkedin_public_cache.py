"""Committed public LinkedIn cache: public fields only, read by default, fresh files win."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from conferge.core.schemas import Person
from conferge.integration import people_linkedin as li

ALLOWED = set(li.PUBLIC_FIELDS)


def _enrichment(url: str, *, headline: str | None) -> li.Enrichment:
    profile = li.LinkedInProfile(linkedin_url=url, name="Ada Lovelace", headline=headline,
                                 title="CTO", company="Analytical", location="London",
                                 about="private-ish text", followers=12, snapshot_id="sd_1",
                                 collected_at="2026-10-24T19:00:00Z")
    return li.Enrichment(person_id="p1", profile=profile, identity_confidence=1.0, company_id=None)


def test_write_public_keeps_only_public_fields(tmp_path: Path) -> None:
    path = li.write_public([_enrichment("https://www.linkedin.com/in/ada/", headline=None)],
                           tmp_path / "public.json")
    entry = json.loads(path.read_text())["profiles"][0]
    assert set(entry) == ALLOWED - {"headline"}  # headline only when present
    assert entry["provider"] == "brightdata:linkedin" and entry["dataset_id"] == li.DATASET_ID
    with_headline = li.write_public([_enrichment("https://www.linkedin.com/in/ada/", headline="Builder")],
                                    tmp_path / "public2.json")
    assert json.loads(with_headline.read_text())["profiles"][0]["headline"] == "Builder"


def test_committed_cache_has_only_public_fields() -> None:
    body = json.loads(li.PUBLIC_CACHE.read_text())
    assert body["profiles"], "data/cache/linkedin_public.json must ship profiles"
    for entry in body["profiles"]:
        assert set(entry) <= ALLOWED
        assert entry["provider"] == "brightdata:linkedin" and entry["linkedin_url"].startswith("https://")


def test_enrich_reads_the_public_cache_and_can_disable_it(tmp_path: Path) -> None:
    url = "https://www.linkedin.com/in/ada/"
    public = li.write_public([_enrichment(url, headline="Old")], tmp_path / "public.json")
    target = Person(id="p1", name="Ada Lovelace", linkedin_url=url)
    empty = tmp_path / "probes"
    empty.mkdir()
    res = asyncio.run(li.enrich([target], [], None, allow_collect=False, directory=empty, public=public))
    assert [e.profile.headline for e in res.enrichments] == ["Old"]
    assert res.enrichments[0].profile.source_mode == "cached"
    assert res.enrichments[0].profile.about is None  # nothing beyond the public fields
    none = asyncio.run(li.enrich([target], [], None, allow_collect=False, directory=empty, public=None))
    assert none.enrichments == []
