import json

import pytest

from conferge.people.fixture import FIXTURE_PATH, build_fixture, load_fixture


def test_fixture_is_explicit_labelled_and_parses():
    with pytest.raises(RuntimeError):
        load_fixture()
    data = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    assert data["source_mode"] == "fixture" and data["label"].startswith("FIXTURE")
    profiles = load_fixture(explicit_opt_in=True)
    assert len(profiles) == data["counts"]["profiles"] > 0
    for p in profiles:
        assert all(e.source_mode == "fixture" and e.collected_at for e in p.person.evidence)
        assert all(x.status == "confirmed" and x.kind in {"speaker", "host"}
                   for x in p.presences)
        person = p.to_person()
        assert person.participation in {"confirmed_speaker", "confirmed_organizer"}


def test_fixture_is_up_to_date_with_sources():
    assert build_fixture()["counts"] == json.loads(
        FIXTURE_PATH.read_text(encoding="utf-8"))["counts"]
