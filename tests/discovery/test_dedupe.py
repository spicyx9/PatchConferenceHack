"""Offline tests for conservative event dedup (fictional events only)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from conferge.core.schemas import Event, SourceEvidence, Venue
from conferge.events.discovery.dedupe import dedupe, normalize_title, normalize_url

LA = ZoneInfo("America/Los_Angeles")
T0 = datetime(2026, 10, 28, 19, 0, tzinfo=LA)


def ev(eid: str, **kw) -> Event:
    base = {"id": eid, "title": "Moonbeam Pancake Social"}
    base.update(kw)
    return Event(**base)


def by_member(groups, eid):
    for g in groups:
        if any(m.id == eid for m in g.members):
            return g
    raise AssertionError(eid)


def test_normalize_title():
    assert normalize_title("  Café   Crème: Night!! ") == "cafe creme night"
    assert normalize_title("MOONBEAM-Pancake  social") == "moonbeam pancake social"


def test_normalize_url():
    a = normalize_url("https://WWW.Lu.ma/abc-123/?utm_source=x#top")
    b = normalize_url("http://lu.ma/abc-123")
    assert a == b


def test_empty_and_unique():
    assert dedupe([]) == []
    groups = dedupe([ev("a", title="Orbit Llama Mixer"), ev("b", title="Velvet Teapot Hack")])
    assert [g.decision for g in groups] == ["unique", "unique"]
    assert all(g.merge_confidence == 1.0 and len(g.members) == 1 for g in groups)


def test_same_source_url():
    a = ev("luma-1", title="Orbit Llama Mixer", source_url="https://lu.ma/orbit-llama?ref=x")
    b = ev("agg-7", title="Orbit Llama Mixer SF!!", source_url="https://lu.ma/orbit-llama/")
    groups = dedupe([a, b])
    assert len(groups) == 1
    g = groups[0]
    assert g.decision == "same"
    assert g.merge_confidence == 1.0
    assert {m.id for m in g.members} == {"luma-1", "agg-7"}
    assert any("same source url" in r for r in g.reasons)


def test_same_url_via_evidence():
    a = ev(
        "a",
        title="Alpha",
        evidence=[SourceEvidence(provider="luma", source_mode="fixture",
                                 source_url="https://lu.ma/zz")],
    )
    b = ev("b", title="Beta", source_url="https://lu.ma/zz/")
    groups = dedupe([a, b])
    assert len(groups) == 1 and groups[0].decision == "same"


def test_same_provider_record_id():
    evid = SourceEvidence(provider="Luma", source_mode="fixture", source_record_id="evt-XYZ")
    evid2 = SourceEvidence(provider="luma", source_mode="live", source_record_id="evt-XYZ")
    groups = dedupe([ev("a", title="One", evidence=[evid]), ev("b", title="Two", evidence=[evid2])])
    assert len(groups) == 1
    assert groups[0].merge_confidence == 1.0
    assert any("record id" in r for r in groups[0].reasons)


def test_title_time_geo_same():
    a = ev("a", start_at=T0, venue=Venue(latitude=37.8060, longitude=-122.4320))
    b = ev(
        "b",
        title="moonbeam pancake SOCIAL",
        start_at=T0 + timedelta(minutes=30),
        venue=Venue(latitude=37.8070, longitude=-122.4330),
    )
    groups = dedupe([a, b])
    assert len(groups) == 1
    g = groups[0]
    assert g.decision == "same"
    assert g.merge_confidence == 0.9
    assert any("m apart" in r for r in g.reasons)


def test_title_time_timezones_compared_in_utc():
    a = ev("a", start_at=T0, organizer_names=["Fizzbang Collective"])
    b = ev("b", start_at=T0.astimezone(timezone.utc), organizer_names=["fizzbang collective"])
    groups = dedupe([a, b])
    assert len(groups) == 1 and groups[0].decision == "same"
    assert any("shared organizer" in r for r in groups[0].reasons)


def test_title_time_same_venue_name():
    a = ev("a", start_at=T0, venue=Venue(name="The Gilded Spoon"))
    b = ev("b", start_at=T0, venue=Venue(name="the gilded spoon!"))
    groups = dedupe([a, b])
    assert len(groups) == 1 and groups[0].decision == "same"


def test_title_only_is_ambiguous():
    a = ev("a")
    b = ev("b", title="Moonbeam Pancake Social!")
    groups = dedupe([a, b])
    assert len(groups) == 2
    assert all(g.decision == "ambiguous" for g in groups)
    ga, gb = by_member(groups, "a"), by_member(groups, "b")
    assert any("b" in r and "start time unknown" in r for r in ga.reasons)
    assert any("a" in r for r in gb.reasons)
    assert ga.merge_confidence == 0.0


def test_title_time_without_corroboration_is_ambiguous():
    a = ev("a", start_at=T0)
    b = ev("b", start_at=T0)
    groups = dedupe([a, b])
    assert len(groups) == 2
    assert all(g.decision == "ambiguous" for g in groups)
    assert any("no location or organizer" in r for r in groups[0].reasons)


def test_far_venues_not_merged():
    a = ev("a", start_at=T0, venue=Venue(latitude=37.8060, longitude=-122.4320))
    b = ev("b", start_at=T0, venue=Venue(latitude=37.7749, longitude=-122.4194))
    groups = dedupe([a, b])
    assert len(groups) == 2
    assert all(g.decision == "ambiguous" for g in groups)


def test_31_minutes_apart_not_same():
    venue = Venue(latitude=37.8060, longitude=-122.4320)
    a = ev("a", start_at=T0, venue=venue)
    b = ev("b", start_at=T0 + timedelta(minutes=31), venue=venue)
    groups = dedupe([a, b])
    assert len(groups) == 2
    assert all(g.decision == "ambiguous" for g in groups)
    assert any("31 min apart" in r for r in groups[0].reasons)


def test_canonical_most_fields_and_tie_first_seen():
    sparse = ev("sparse", source_url="https://lu.ma/x")
    rich = ev(
        "rich",
        source_url="https://lu.ma/x",
        description="Pancakes under the stars",
        start_at=T0,
        organizer_names=["Fizzbang Collective"],
    )
    g = dedupe([sparse, rich])[0]
    assert g.canonical.id == "rich"
    assert [m.id for m in g.members] == ["sparse", "rich"]
    tie = dedupe([ev("first", source_url="https://lu.ma/y"),
                  ev("second", source_url="https://lu.ma/y")])[0]
    assert tie.canonical.id == "first"


def test_transitive_grouping_keeps_all_rows():
    a = ev("a", source_url="https://lu.ma/q")
    b = ev("b", source_url="https://lu.ma/q",
           evidence=[SourceEvidence(provider="eventbrite", source_mode="fixture",
                                    source_record_id="999")])
    c = ev("c", evidence=[SourceEvidence(provider="eventbrite", source_mode="fixture",
                                         source_record_id="999")])
    groups = dedupe([a, b, c])
    assert len(groups) == 1
    assert {m.id for m in groups[0].members} == {"a", "b", "c"}


def test_input_not_mutated():
    a = ev("a", start_at=T0, venue=Venue(latitude=37.8060, longitude=-122.4320),
           source_url="https://lu.ma/m")
    b = ev("b", start_at=T0, venue=Venue(latitude=37.8060, longitude=-122.4320))
    before = [a.model_dump(), b.model_dump()]
    groups = dedupe([a, b])
    assert [a.model_dump(), b.model_dump()] == before
    assert groups[0].members[0] is not a
