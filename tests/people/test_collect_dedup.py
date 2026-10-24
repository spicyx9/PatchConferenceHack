from people_testkit import NOW, profile

from conferge.core.schemas import Company, Event, Person, SourceEvidence, SourceRecord
from conferge.people.collect import collect_fixtures, from_luma, from_official
from conferge.people.dedup import dedupe


def _ev():
    return SourceEvidence(provider="rainfocus:test", source_mode="fixture",
                          source_url="https://example.org/catalog", collected_at=NOW)


def test_from_official_confirms_only_listed_sessions():
    person = Person(id="person:rf:1", name="Avery Example", title="Co-founder",
                    company_id="company:example-labs", participation="confirmed_speaker",
                    event_ids=["ev-1"], evidence=[_ev()], roles=["investor"])
    events = [Event(id="ev-1", title="Building MCP servers for AI agents",
                    source_url="https://example.org/s/1")]
    [p] = from_official([person], events,
                        [Company(id="company:example-labs", name="Example Labs")])
    assert p.company_name == "Example Labs"
    assert [(x.event_id, x.kind, x.status) for x in p.presences] == [
        ("ev-1", "speaker", "confirmed")]
    assert str(p.presences[0].evidence.source_url) == "https://example.org/s/1"
    assert p.person.roles == ["founder"]  # re-derived from title, source guess dropped
    assert {"mcp", "ai agents"} <= set(p.person.topics)
    assert p.talk_titles == ["Building MCP servers for AI agents"]


def test_from_luma_hosts_only_never_guests():
    record = SourceRecord(
        provider="luma:public", source_id="evt-abc", source_mode="fixture", collected_at=NOW,
        source_url="https://luma.com/abc",
        payload={"hosts": [{"api_id": "usr-1", "name": "Blake Sample"}, {"name": "no id"}],
                 "guests": [{"api_id": "usr-2", "name": "Private Guest"}]},
    )
    event = Event(id="luma:evt-abc", title="AI agents happy hour")
    [p] = from_luma([record, record], [event])
    assert p.person.name == "Blake Sample"
    assert len(p.presences) == 1 and p.presences[0].kind == "host"
    assert p.person.evidence[0].source_mode == "fixture"
    assert p.person.linkedin_url is None


def test_dedup_merges_on_declared_url_and_name_company():
    a = profile("person:a", "Avery Example", company_id="company:x",
                linkedin="https://www.linkedin.com/in/avery-example/",
                presences=[("ev-talk", "speaker", "confirmed")])
    b = profile("person:b", "Avery Example", company_id="company:x", topics=["mcp"],
                presences=[("ev-party", "host", "confirmed")])
    c = profile("person:c", "A. Example", linkedin="https://linkedin.com/in/avery-example")
    merged, amb = dedupe([a, b, c])
    assert len(merged) == 1 and not amb
    m = merged[0]
    assert set(m.merged_from) == {"person:a", "person:b", "person:c"}
    assert {(p.event_id, p.kind) for p in m.presences} == {
        ("ev-talk", "speaker"), ("ev-party", "host")}
    assert "mcp" in m.person.topics


def test_dedup_name_only_is_ambiguous_not_merged():
    a = profile("person:a", "Casey Placeholder", company_id="company:x")
    b = profile("person:b", "casey placeholder")
    c = profile("person:c", "Casey Placeholder", company_id="company:y")
    merged, amb = dedupe([a, b, c])
    assert len(merged) == 3
    assert len(amb) == 3
    assert any(x.reason == "same name, different companies" for x in amb)


def test_collect_fixtures_requires_opt_in_and_stays_fixture():
    import pytest

    with pytest.raises(RuntimeError):
        collect_fixtures()
    collected = collect_fixtures(explicit_opt_in=True)
    assert collected.source_mode == "fixture"
    assert collected.profiles
    for p in collected.profiles:
        assert all(e.source_mode == "fixture" for e in p.person.evidence)
        assert all(x.kind in {"speaker", "host"} for x in p.presences)
