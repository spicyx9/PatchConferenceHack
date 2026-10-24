from fastapi.testclient import TestClient

from conferge.api.app import create_app
from conferge.api.data import load_fixture
from conferge.api.network_roster import extend, models
from conferge.api.providers import Providers


def test_public_roster_has_sources_but_no_claimed_attendance():
    people, companies = models()
    assert len(people) == 10
    assert len({p.id for p in people}) == 10
    assert sum('founder' in p.roles for p in people) == 5
    assert all(p.participation == 'relevant_candidate' and not p.event_ids for p in people)
    assert all(p.evidence[0].source_url and p.evidence[0].collected_at for p in people)
    assert all(p.company_id in {c.id for c in companies} for p in people)


def test_roster_is_opt_in_idempotent_and_preserves_input(monkeypatch):
    data = load_fixture()
    before = len(data.people)
    expanded = extend(data)
    assert len(data.people) == before
    assert len(expanded.people) == before + 10
    assert len(extend(expanded).people) == len(expanded.people)
    monkeypatch.delenv('CONFERGE_NETWORK_ROSTER', raising=False)
    plain = TestClient(create_app(data=data, found=Providers(), graph_probe=False))
    assert plain.get('/api/v1/connections').json()['count'] == before
    monkeypatch.setenv('CONFERGE_NETWORK_ROSTER', '1')
    client = TestClient(create_app(data=data, found=Providers(), graph_probe=False))
    result = client.get('/api/v1/connections?role=investor').json()
    additions = [p for p in result['items'] if p['id'].startswith('public:')]
    assert len(additions) == 10
    assert all(p['participation'] == 'relevant_candidate' and not p['events'] for p in additions)
