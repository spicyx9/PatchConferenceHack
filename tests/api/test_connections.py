"""Membership, provider failure and vector validation contracts."""
import json
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from conferge.api import connections as c
from conferge.api.app import create_app
from conferge.api.providers import Providers


def test_offline_search_and_scopes(monkeypatch):
    monkeypatch.setattr(c, 'key', lambda: None)
    client = TestClient(create_app(found=Providers(), graph_probe=False))
    directory = client.get('/api/v1/connections').json()
    assert directory['count'] > 0
    response = client.post('/api/v1/connections/search', json={'query': 'AI'})
    assert response.status_code == 200
    assert response.json()['mode'] == 'keyword'
    assert {p['id'] for p in response.json()['items']} <= {p['id'] for p in directory['items']}
    assert client.post('/api/v1/connections/search', json={'query': 'AI', 'scope': 'met'}).json()['items'] == []
    assert client.post('/api/v1/connections/search', json={'query': 'x'}).status_code == 422
    assert client.get('/api/v1/connections?scope=other').status_code == 422


@pytest.mark.parametrize('vector', [[0.0], [float('nan')] * 512, ['x'] * 512])
def test_bad_vectors_rejected(vector):
    with pytest.raises(ValueError):
        c.VectorStore._properties({c.VECTOR_PROPERTY: vector}, 'n')


def test_typed_vector_write():
    clause, params = c.VectorStore._properties({c.VECTOR_PROPERTY: [0.0] * 512}, 'n')
    assert 'vecf32($prop_0)' in clause
    assert len(params['prop_0']) == 512


@pytest.mark.asyncio
async def test_model_cannot_add_people_or_duplicates(monkeypatch):
    result = {'summary': 'Matches', 'matches': [{'id': 'outside', 'reason': 'no'},
              {'id': 'inside', 'reason': 'supported'}, {'id': 'inside', 'reason': 'duplicate'}]}
    mock = AsyncMock(return_value={'output': [{'content': [{'type': 'output_text', 'text': json.dumps(result)}]}]})
    monkeypatch.setattr(c, 'openai_post', mock)
    actual = await c.explain('find people', [{'id': 'inside', 'name': 'Known person'}])
    assert actual['items'] == [{'id': 'inside', 'name': 'Known person', 'reason': 'supported'}]


@pytest.mark.asyncio
async def test_bad_embedding_response_rejected(monkeypatch):
    monkeypatch.setattr(c, 'openai_post', AsyncMock(return_value={'data': [{'index': 1, 'embedding': [0.0] * 512}]}))
    with pytest.raises(ValueError):
        await c.embed(['profile'])


def test_overview_keeps_every_person_and_focus_is_scoped(monkeypatch):
    from types import SimpleNamespace

    from conferge.graph import queries

    monkeypatch.setattr(queries, 'path_user_to_person', lambda *args: {'paths': []})
    graph = SimpleNamespace(query=lambda *args, **kwargs: SimpleNamespace(result_set=[]))
    state = SimpleNamespace(store=lambda: SimpleNamespace(graph=graph), opportunities=lambda: [])
    items = [{'id': f'p{i}', 'name': f'Person {i}', 'source_mode': 'fixture'} for i in range(50)]
    overview = c.graph_view(state, items, None)
    assert {n['id'] for n in overview['nodes']} == {p['id'] for p in items}
    focused = c.graph_view(state, items, 'p9')
    assert [n['id'] for n in focused['nodes']] == ['p9']
    assert 'outsider' not in {n['id'] for n in c.graph_view(state, items, 'outsider')['nodes']}
