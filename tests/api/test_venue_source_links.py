from datetime import datetime, timezone

from fastapi.testclient import TestClient

from conferge.api.app import create_app
from conferge.api.data import load_fixture
from conferge.api.providers import Providers
from conferge.core.schemas import SourceEvidence


def test_cached_maps_place_id_gets_source_link_without_mutating_evidence():
    data = load_fixture()
    event = next(e for e in data.events if e.venue)
    evidence = SourceEvidence(provider='brightdata:google_maps', source_mode='cached',
                              source_record_id='ChIJ-example', collected_at=datetime.now(timezone.utc))
    event.evidence.append(evidence)
    client = TestClient(create_app(data=data, found=Providers(), graph_probe=False))
    row = next(e for e in client.get('/api/v1/events').json()['items'] if e['id'] == event.id)
    source = row['evidence'][-1]
    assert 'query_place_id=ChIJ-example' in source['source_url']
    assert source['collected_at']
    assert evidence.source_url is None
