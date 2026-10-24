"""Sourced public candidates, separate from conference attendance and fictional fixtures.

Enable the local directory with CONFERGE_NETWORK_ROSTER=1.
Import graph records and cache official headshots: python -m conferge.api.network_roster
"""
from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import httpx

from conferge.api.data import DemoData
from conferge.api.photos import CACHE, MANIFEST, image_format, manifest
from conferge.core.schemas import Company, Person, SourceEvidence

ROSTER = Path(__file__).with_name('network_roster.json')


def records() -> list[dict]:
    return json.loads(ROSTER.read_text())


def models() -> tuple[list[Person], list[Company]]:
    people, companies = [], {}
    for row in records():
        evidence = [SourceEvidence(provider=row['company'] + ' official team', source_mode='cached',
                                   source_url=row['source_url'], collected_at=row['collected_at'])]
        cid = 'public-company:' + row['company'].lower()
        companies[cid] = Company(id=cid, name=row['company'], is_investor=True, evidence=evidence)
        people.append(Person(id=row['id'], name=row['name'], title=row['title'], role=row['title'],
                             company_id=cid, bio=row['bio'], topics=row['topics'], roles=row['roles'],
                             public_profile_url=row['source_url'], participation='relevant_candidate',
                             evidence=evidence))
    return people, list(companies.values())


def extend(data: DemoData) -> DemoData:
    """Copy the supplied snapshot; do not mutate the runner's input or duplicate identities."""
    result = copy.deepcopy(data)
    people, companies = models()
    names = {p.name.casefold() for p in result.people}
    ids = {p.id for p in result.people}
    additions = [p for p in people if p.id not in ids and p.name.casefold() not in names]
    company_ids = {p.company_id for p in additions} - {c.id for c in result.companies}
    result.people.extend(additions)
    result.companies.extend(c for c in companies if c.id in company_ids)
    for domain in ('people', 'companies'):
        if additions and domain in result.domains and result.domains[domain].source_mode != 'cached':
            result.domains[domain].source_mode = 'mixed'
    return result


def enrich() -> None:
    from conferge.core.store import connect_graph
    from conferge.graph.ingest import GraphIngestor

    store = connect_graph()
    people, companies = models()
    ingestor = GraphIngestor(store, default_mode='cached')
    ingestor.ingest_companies(companies)
    ingestor.ingest_people(people)
    CACHE.mkdir(parents=True, exist_ok=True)
    photos = dict(manifest())
    saved = failed = 0
    with httpx.Client(timeout=30, follow_redirects=True) as client:
        for row in records():
            if row['id'] in photos:
                continue
            try:
                body = bytearray()
                with client.stream('GET', row['photo_source_url']) as response:
                    response.raise_for_status()
                    for chunk in response.iter_bytes():
                        body.extend(chunk)
                        if len(body) > 5_000_000:
                            raise ValueError('oversized photo')
                kind = image_format(bytes(body))
                if not kind:
                    raise ValueError('unsupported image')
                filename = hashlib.sha256(row['id'].encode()).hexdigest()[:24] + kind[0]
                (CACHE / filename).write_bytes(body)
                photos[row['id']] = dict(filename=filename, media_type=kind[1], source_url=row['source_url'],
                                         provider='official:' + row['company'], source_mode='live',
                                         collected_at=datetime.now(timezone.utc).isoformat())
                temporary = MANIFEST.with_suffix('.tmp')
                temporary.write_text(json.dumps(photos, indent=2))
                temporary.replace(MANIFEST)
                store.merge_node('Person', row['id'], {
                    'photo_url': '/api/v1/connections/photos/' + filename,
                    'photo_source_url': row['source_url'], 'photo_provider': photos[row['id']]['provider'],
                    'photo_collected_at': photos[row['id']]['collected_at']})
                saved += 1
                print('Saved ' + row['name'], flush=True)
            except Exception as exc:
                failed += 1
                print(f"Photo failed for {row['name']}: {type(exc).__name__}", flush=True)
    print(json.dumps(dict(people=len(people), saved=saved, failed=failed, total_cached=len(photos))))
    if failed:
        raise SystemExit(1)


if __name__ == '__main__':
    enrich()
