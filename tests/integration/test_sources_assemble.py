from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from conferge.core.schemas import Event, SourceEvidence
from conferge.integration.assemble import assemble
from conferge.integration.sources import SourceSlice, fixture_slices, live_slices

NOW = datetime(2026, 10, 24, 12, 0, tzinfo=timezone.utc)


def _event(eid: str, url: str | None, provider: str = "test") -> Event:
    return Event(
        id=eid, title=f"Event {eid}", source_url=url,
        evidence=[SourceEvidence(provider=provider, source_mode="fixture", collected_at=NOW)],
    )


def test_fixture_slices_are_labelled_and_timestamped(no_network: None) -> None:
    slices = fixture_slices()
    assert {s.name for s in slices} == {"official", "luma", "partiful", "eventbrite",
                                        "aggregators", "discovery"}
    discovery = next(s for s in slices if s.name == "discovery")
    assert discovery.count == 0  # SERP hits are candidate URLs, never events
    assert "candidate URLs" in discovery.warnings[0]
    for s in slices:
        if s.name == "discovery":
            continue
        assert s.attempted == "fixture"
        assert s.source_mode == "fixture", s.name
        assert s.status != "failed", (s.name, s.errors)
        assert s.count > 0, s.name
        assert s.collected_at is not None and s.collected_at.tzinfo is not None
        for item in [*s.events, *s.people, *s.companies]:
            assert item.evidence, item.id
            assert all(ev.source_mode == "fixture" and ev.collected_at for ev in item.evidence)


def test_side_events_are_not_attached_to_the_conference(no_network: None) -> None:
    for s in fixture_slices(["luma", "partiful", "eventbrite"]):
        assert all(e.conference_id is None for e in s.events), s.name


def test_live_failure_stays_failed_and_empty() -> None:
    async def boom() -> SourceSlice:
        raise RuntimeError("HTTP 503 from provider")

    async def slow() -> SourceSlice:
        await asyncio.sleep(5)
        raise AssertionError("unreachable")

    out = asyncio.run(live_slices(runners={"boom": ("01", boom), "slow": ("02", slow)},
                                  timeout=0.05))
    by_name = {s.name: s for s in out}
    assert by_name["boom"].status == "failed"
    assert by_name["boom"].source_mode == "live"
    assert by_name["boom"].count == 0
    assert "HTTP 503" in by_name["boom"].errors[0]
    assert "timeout" in by_name["slow"].errors[0]


def test_assemble_uses_official_conference_and_labels_missing_domains(no_network: None) -> None:
    assembly = assemble(fixture_slices())
    assert assembly.conference.id == "github-universe-2026"
    assert assembly.conference_origin.startswith("official")
    assert assembly.data_mode == "fixture"
    domains = assembly.demo.domains
    assert domains["events"].source_mode == "fixture"
    assert domains["stays"].source_mode == "fixture"
    assert any("w05" in w for w in domains["stays"].warnings)
    assert any("w06" in w for w in domains["flights"].warnings)
    assert any("conference id mismatch" in w for w in assembly.warnings)
    # Official sessions share the catalog URL: that URL must not collapse them.
    official = next(s for s in fixture_slices(["official"]))
    assert len([e for e in assembly.events if e.id in {x.id for x in official.events}]) == len(
        official.events)


def test_cross_source_same_page_is_listed_not_merged() -> None:
    a = SourceSlice("a", "01", "fixture", "fixture", "ok", events=[_event("a1", "https://x.test/e/1")],
                    collected_at=NOW)
    b = SourceSlice("b", "02", "fixture", "fixture", "ok",
                    events=[_event("b1", "https://x.test/e/1"), _event("b2", None)],
                    collected_at=NOW)
    assembly = assemble([a, b])
    assert [e.id for e in assembly.events] == ["a1", "b2"]
    assert assembly.duplicates == ["b1 same source_url as a1"]
    assert assembly.conference_origin == "fixtures/api.json (fixture)"


def test_mixed_modes_are_reported_mixed() -> None:
    live = SourceSlice("l", "01", "live", "live", "ok", events=[_event("l1", None)],
                       collected_at=NOW)
    fx = SourceSlice("f", "02", "fixture", "fixture", "ok", events=[_event("f1", None)],
                     collected_at=NOW)
    assembly = assemble([live, fx])
    assert assembly.data_mode == "mixed"
    assert assembly.demo.domains["events"].source_mode == "mixed"
