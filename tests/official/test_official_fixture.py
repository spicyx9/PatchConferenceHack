"""The committed fixture parses into core schemas and is never presented as live."""

from __future__ import annotations

import json

import pytest

from conferge.core.schemas import Company, Conference, Event, Person
from conferge.events.official.source import FIXTURE_PATH, load_fixture


def test_fixture_requires_explicit_opt_in():
    with pytest.raises(RuntimeError):
        load_fixture()


def test_fixture_is_labelled_and_parses():
    raw = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    assert raw["source_mode"] == "fixture" and raw["label"].startswith("FIXTURE")
    assert raw["captured_at"] and raw["source_urls"]

    collection = load_fixture(explicit_opt_in=True)
    assert collection.source_mode == "fixture"
    assert collection.events.reports[0].source_mode == "fixture"
    assert any("FIXTURE" in w for w in collection.events.reports[0].warnings)
    assert isinstance(collection.conference, Conference)
    assert collection.events.items and collection.people.items and collection.companies.items

    for event in collection.events.items:
        Event.model_validate(event.model_dump())
        assert event.evidence and event.evidence[0].source_mode == "fixture"
        assert event.evidence[0].collected_at is not None
        assert event.conference_relation in {"official", "confirmed_side_event"}
        assert event.relation_evidence
        if event.start_at is not None:
            assert event.start_at.tzinfo is not None
    for person in collection.people.items:
        Person.model_validate(person.model_dump())
        assert person.participation == "confirmed_speaker"
        assert person.event_ids, "a confirmed speaker must be tied to an official listing"
        assert person.evidence[0].source_mode == "fixture"
    for company in collection.companies.items:
        Company.model_validate(company.model_dump())

    event_ids = {e.id for e in collection.events.items}
    assert all(set(p.event_ids) <= event_ids for p in collection.people.items)
    sponsors = [c for c in collection.companies.items if "sponsor" in c.categories]
    assert set(collection.conference.sponsor_ids) == {c.id for c in sponsors}


def test_fixture_has_no_prices_or_secrets():
    text = FIXTURE_PATH.read_text(encoding="utf-8").lower()
    for marker in ("apiprofiletoken", "rfapiprofileid", "authorization: bearer", "set-cookie"):
        assert marker not in text
    collection = load_fixture(explicit_opt_in=True)
    assert all(e.price_min is None and e.price_max is None for e in collection.events.items)
