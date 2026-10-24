"""Offline tests for event to conference linking (fictional events only)."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from conferge.core.schemas import Conference, Event, Venue
from conferge.events.discovery.link import (
    INCLUSION_THRESHOLD,
    WEIGHTS,
    apply_link,
    haversine_km,
    link_to_conference,
)

LA = ZoneInfo("America/Los_Angeles")
FORT_MASON = (37.8060, -122.4320)
SPONSORS = ["Zyntrix Cloud Labs", "Acme Widgets Inc."]
SPEAKERS = ["Quill Fernsby"]


@pytest.fixture
def conf() -> Conference:
    return Conference(
        id="github-universe-2026",
        name="GitHub Universe",
        start_date=date(2026, 10, 28),
        end_date=date(2026, 10, 29),
        city="San Francisco",
        venue_name="Fort Mason Center",
        timezone="America/Los_Angeles",
        latitude=FORT_MASON[0],
        longitude=FORT_MASON[1],
        topics=["AI agents", "developer tools", "Copilot", "MCP"],
    )


def make_event(**kw) -> Event:
    base = {"id": "evt-1", "title": "Moonbeam Pancake Social"}
    base.update(kw)
    return Event(**base)


def full_event() -> Event:
    return make_event(
        title="Zyntrix GitHub Universe Afterglow",
        description="Drinks and demos about AI agents after day one.",
        start_at=datetime(2026, 10, 28, 19, 0, tzinfo=LA),
        venue=Venue(name="Pier Shack", latitude=37.8050, longitude=-122.4300),
        organizer_names=["Zyntrix Cloud Labs"],
    )


def full_kwargs() -> dict:
    return {
        "sponsor_names": SPONSORS,
        "speaker_names": SPEAKERS,
        "listed_on_aggregator": True,
    }


def test_weights_sum_to_one():
    assert sum(WEIGHTS.values()) == pytest.approx(1.0)
    assert INCLUSION_THRESHOLD == 0.5


def test_full_score(conf):
    score, signals = link_to_conference(full_event(), conf, **full_kwargs())
    assert score == 1.0
    assert set(signals) == set(WEIGHTS)
    assert all(s["value"] is True for s in signals.values())
    assert all(isinstance(s["detail"], str) and s["detail"] for s in signals.values())


def test_zero_score_all_unknown(conf):
    score, signals = link_to_conference(make_event(), conf)
    assert score == 0.0
    assert all(s["value"] is False for s in signals.values())
    assert signals["date_within_window"]["detail"] == "start unknown"
    assert signals["geo_within_radius"]["detail"] == "venue coordinates unknown"
    assert signals["host_is_sponsor_or_speaker"]["detail"] == "organizers unknown"
    assert "lexical fallback" in signals["topic_overlap"]["detail"]


def test_mention_alias_word_boundary(conf):
    ev = make_event(title="Pre-Universe Robot Brunch")
    score, s = link_to_conference(ev, conf, aliases=["Universe"])
    assert s["mentions_conference"]["value"] is True
    assert score == 0.3
    ev2 = make_event(title="Universes of Toast")
    _, s2 = link_to_conference(ev2, conf, aliases=["Universe"])
    assert s2["mentions_conference"]["value"] is False


def test_mention_case_insensitive_in_description(conf):
    ev = make_event(description="see you at github   universe next week")
    _, s = link_to_conference(ev, conf)
    assert s["mentions_conference"]["value"] is True


def test_threshold_candidate_and_unknown(conf):
    # mention 0.3 + date 0.2 = 0.5 exactly -> candidate
    ev = make_event(
        title="GitHub Universe Waffle Hour",
        start_at=datetime(2026, 10, 28, 9, 0, tzinfo=LA),
    )
    linked = apply_link(ev, conf)
    assert linked.relation_score == 0.5
    assert linked.conference_relation == "candidate"
    assert linked.conference_id == "github-universe-2026"
    assert any(e.startswith("mentions_conference") for e in linked.relation_evidence)
    assert any(e.startswith("date_within_window") for e in linked.relation_evidence)
    # mention 0.3 + geo 0.15 = 0.45 -> unknown
    ev2 = make_event(
        title="GitHub Universe Waffle Hour",
        venue=Venue(latitude=37.80, longitude=-122.43),
    )
    linked2 = apply_link(ev2, conf)
    assert linked2.relation_score == 0.45
    assert linked2.conference_relation == "unknown"
    assert linked2.conference_id == "github-universe-2026"


def test_apply_link_never_official(conf):
    linked = apply_link(full_event(), conf, **full_kwargs())
    assert linked.relation_score == 1.0
    assert linked.conference_relation == "candidate"
    assert len(linked.relation_evidence) == len(WEIGHTS)


def test_apply_link_keeps_existing_official(conf):
    ev = make_event(
        conference_relation="official",
        relation_evidence=["listed on githubuniverse.com agenda"],
    )
    linked = apply_link(ev, conf)
    assert linked.conference_relation == "official"
    assert linked.relation_evidence == ["listed on githubuniverse.com agenda"]
    assert linked.relation_score == 0.0
    assert linked.conference_id == "github-universe-2026"
    assert ev.relation_score is None  # input untouched


def test_apply_link_keeps_confirmed_side_event(conf):
    ev = make_event(
        conference_id="github-universe-2026",
        conference_relation="confirmed_side_event",
        relation_evidence=["organizer page says official side event"],
    )
    linked = apply_link(ev, conf, **full_kwargs())
    assert linked.conference_relation == "confirmed_side_event"
    assert linked.relation_evidence == ["organizer page says official side event"]


def test_apply_link_does_not_mutate_input(conf):
    ev = full_event()
    before = ev.model_dump()
    apply_link(ev, conf, **full_kwargs())
    assert ev.model_dump() == before


@pytest.mark.parametrize(
    ("day", "expected"),
    [
        (date(2026, 10, 25), False),
        (date(2026, 10, 26), True),
        (date(2026, 10, 28), True),
        (date(2026, 10, 31), True),
        (date(2026, 11, 1), False),
    ],
)
def test_date_window_edges(conf, day, expected):
    ev = make_event(start_at=datetime(day.year, day.month, day.day, 12, 0, tzinfo=LA))
    _, s = link_to_conference(ev, conf)
    assert s["date_within_window"]["value"] is expected


def test_date_window_custom_days(conf):
    ev = make_event(start_at=datetime(2026, 10, 27, 12, 0, tzinfo=LA))
    _, s = link_to_conference(ev, conf, window_days=0)
    assert s["date_within_window"]["value"] is False


def test_date_timezone_conversion_at_utc_midnight(conf):
    # 2026-11-01 05:00 UTC is 2026-10-31 22:00 PDT -> inside window.
    ev = make_event(start_at=datetime(2026, 11, 1, 5, 0, tzinfo=timezone.utc))
    _, s = link_to_conference(ev, conf)
    assert s["date_within_window"]["value"] is True
    assert "2026-10-31" in s["date_within_window"]["detail"]
    # 2026-10-26 02:00 UTC is 2026-10-25 19:00 PDT -> outside window.
    ev2 = make_event(start_at=datetime(2026, 10, 26, 2, 0, tzinfo=timezone.utc))
    _, s2 = link_to_conference(ev2, conf)
    assert s2["date_within_window"]["value"] is False


def _point_at_km(km: float) -> tuple[float, float]:
    # Move due north; 1 degree latitude ~ 111.19 km on this sphere.
    lat0, lng0 = FORT_MASON
    deg = km / (haversine_km(lat0, lng0, lat0 + 1.0, lng0))
    return lat0 + deg, lng0


def test_radius_edge(conf):
    lat_in, lng_in = _point_at_km(7.99)
    lat_out, lng_out = _point_at_km(8.01)
    _, s_in = link_to_conference(make_event(venue=Venue(latitude=lat_in, longitude=lng_in)), conf)
    _, s_out = link_to_conference(
        make_event(venue=Venue(latitude=lat_out, longitude=lng_out)), conf
    )
    assert s_in["geo_within_radius"]["value"] is True
    assert s_out["geo_within_radius"]["value"] is False
    _, s_wide = link_to_conference(
        make_event(venue=Venue(latitude=lat_out, longitude=lng_out)), conf, radius_km=9.0
    )
    assert s_wide["geo_within_radius"]["value"] is True


def test_same_city_without_coordinates_is_not_within_radius(conf):
    ev = make_event(venue=Venue(name="Somewhere", city="san francisco"))
    _, s = link_to_conference(ev, conf)
    assert s["geo_within_radius"]["value"] is False
    assert s["geo_within_radius"]["detail"] == "same city, no coordinates"


def test_sponsor_matching_normalized(conf):
    ev = make_event(organizer_names=["ZYNTRIX, Cloud-Labs"])
    _, s = link_to_conference(ev, conf, sponsor_names=SPONSORS)
    assert s["host_is_sponsor_or_speaker"]["value"] is True
    assert "sponsor" in s["host_is_sponsor_or_speaker"]["detail"]


def test_sponsor_containment_both_directions(conf):
    # organizer contains sponsor
    ev = make_event(organizer_names=["Acme Widgets Inc. Dev Relations Team"])
    _, s = link_to_conference(ev, conf, sponsor_names=SPONSORS)
    assert s["host_is_sponsor_or_speaker"]["value"] is True
    # sponsor contains organizer
    ev2 = make_event(organizer_names=["Acme Widgets"])
    _, s2 = link_to_conference(ev2, conf, sponsor_names=SPONSORS)
    assert s2["host_is_sponsor_or_speaker"]["value"] is True


def test_speaker_matching_and_partial_token_rejected(conf):
    ev = make_event(organizer_names=["Quill Fernsby"])
    _, s = link_to_conference(ev, conf, speaker_names=SPEAKERS)
    assert s["host_is_sponsor_or_speaker"]["value"] is True
    assert "speaker" in s["host_is_sponsor_or_speaker"]["detail"]
    # "Zyn" is a substring but not a whole token of the sponsor name.
    ev2 = make_event(organizer_names=["Zyn"])
    _, s2 = link_to_conference(ev2, conf, sponsor_names=SPONSORS)
    assert s2["host_is_sponsor_or_speaker"]["value"] is False


def test_short_names_ignored(conf):
    ev = make_event(organizer_names=["AB"])
    _, s = link_to_conference(ev, conf, sponsor_names=["AB Ventures"])
    assert s["host_is_sponsor_or_speaker"]["value"] is False


def test_topic_lexical_fallback(conf):
    ev = make_event(description="Hands-on with copilot extensions")
    _, s = link_to_conference(ev, conf)
    assert s["topic_overlap"]["value"] is True
    assert "lexical fallback" in s["topic_overlap"]["detail"]
    assert "Copilot" in s["topic_overlap"]["detail"]


def test_topic_fallback_uses_event_topics(conf):
    ev = make_event(topics=["mcp"])
    _, s = link_to_conference(ev, conf)
    assert s["topic_overlap"]["value"] is True


def test_topic_fallback_requires_whole_phrase(conf):
    ev = make_event(description="Agents of the AI-free knitting circle, MCPX lovers")
    _, s = link_to_conference(ev, conf)
    assert s["topic_overlap"]["value"] is False


def test_topic_similarity_overrides_fallback(conf):
    ev = make_event(description="copilot copilot")
    _, low = link_to_conference(ev, conf, topic_similarity=0.35)
    assert low["topic_overlap"]["value"] is False
    _, high = link_to_conference(make_event(), conf, topic_similarity=0.36)
    assert high["topic_overlap"]["value"] is True


def test_score_rounding_and_range(conf):
    ev = make_event(
        start_at=datetime(2026, 10, 29, 18, 0, tzinfo=LA),
        venue=Venue(latitude=37.79, longitude=-122.41),
    )
    score, _ = link_to_conference(ev, conf, listed_on_aggregator=True)
    assert score == 0.4
    assert 0.0 <= score <= 1.0
    assert round(score, 4) == score


def test_end_before_window_irrelevant(conf):
    # Only start_at drives the date signal.
    ev = make_event(
        start_at=datetime(2026, 10, 31, 23, 0, tzinfo=LA),
        end_at=datetime(2026, 10, 31, 23, 0, tzinfo=LA) + timedelta(hours=4),
    )
    _, s = link_to_conference(ev, conf)
    assert s["date_within_window"]["value"] is True
