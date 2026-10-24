"""fixtures/graph.json is explicit, fictional, provenance-tagged fixture data."""

from __future__ import annotations

import pytest

from conferge.graph.seed import load_graph_fixture


@pytest.fixture(scope="module")
def bundle():
    return load_graph_fixture()


def test_fixture_parses_as_fixture_mode(bundle):
    assert bundle.source_mode == "fixture"
    assert bundle.people and bundle.events and bundle.companies


def test_every_record_has_fixture_evidence(bundle):
    records = [*bundle.people, *bundle.events, *bundle.companies, bundle.conference]
    for record in records:
        assert record.evidence, record.id
        for evidence in record.evidence:
            assert evidence.source_mode == "fixture", record.id
            assert evidence.collected_at is not None, record.id
            assert evidence.collected_at.tzinfo is not None, record.id


def test_fictional_records_are_labelled(bundle):
    for person in bundle.people:
        assert "Fixture" in person.name, person.id
    for company in bundle.companies:
        assert "Fixture" in company.name, company.id
    for event in bundle.events:
        assert event.title.startswith("[FIXTURE]"), event.id


def test_no_invented_prices(bundle):
    assert bundle.lodging == []
    assert bundle.flights == []
    for event in bundle.events:
        assert event.price_min is None and event.price_max is None, event.id
