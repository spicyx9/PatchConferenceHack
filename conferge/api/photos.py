"""Local, attributed photo cache; no credentials or expiring CDN URLs reach the browser.

Run: FALKORDB_PORT=6380 FALKORDB_GRAPH=conferge_demo uv run python -m conferge.api.photos
"""
from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse

import httpx

from conferge.core.brightdata import BrightDataClient
from conferge.core.settings import env_value
from conferge.core.store import connect_graph

CACHE = Path(__file__).resolve().parents[2] / 'raw' / 'connection-photos'
MANIFEST = CACHE / 'manifest.json'
_cached_stamp = None
_cached_manifest: dict = {}


def manifest() -> dict:
    global _cached_stamp, _cached_manifest
    stamp = MANIFEST.stat().st_mtime_ns if MANIFEST.exists() else None
    if stamp != _cached_stamp:
        _cached_manifest = json.loads(MANIFEST.read_text()) if stamp else {}
        _cached_stamp = stamp
    return _cached_manifest


class ImageMeta(HTMLParser):
    def __init__(self):
        super().__init__()
        self.url = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'meta' and attrs.get('property') == 'og:image':
            url = attrs.get('content', '')
            parsed = urlparse(url)
            if parsed.scheme == 'https' and parsed.hostname == 'media.licdn.com' and 'profile-displayphoto' in parsed.path:
                self.url = url


def image_format(body: bytes) -> tuple[str, str] | None:
    if body.startswith(b'\xff\xd8\xff'):
        return '.jpg', 'image/jpeg'
    if body.startswith(b'\x89PNG\r\n\x1a\n'):
        return '.png', 'image/png'
    if body[:4] == b'RIFF' and body[8:12] == b'WEBP':
        return '.webp', 'image/webp'
    return None


async def enrich(names: set[str] | None = None) -> None:
    CACHE.mkdir(parents=True, exist_ok=True)
    records = dict(manifest())
    store = connect_graph()
    async with httpx.AsyncClient(timeout=30) as local:
        directory = (await local.get('http://127.0.0.1:8000/api/v1/connections')).json()['items']
    allowed = {p['id'] for p in directory}
    rows = store.graph.query('MATCH (p:Person) WHERE p.linkedin_url IS NOT NULL RETURN p.id, p.name, p.linkedin_url').result_set
    targets = [(pid, name, url) for pid, name, url in rows if pid in allowed and pid not in records and (names is None or name in names)
               and urlparse(url).hostname in ('www.linkedin.com', 'linkedin.com') and urlparse(url).path.startswith('/in/')]
    print(f'Enrichment: {len(targets)} linked profiles; {len(records)} cached photos', flush=True)
    semaphore = asyncio.Semaphore(8)
    outcomes = {'saved': 0, 'unavailable': 0, 'failed': 0}
    async with httpx.AsyncClient(base_url='https://api.brightdata.com', timeout=60) as transport, httpx.AsyncClient(timeout=25) as images:
        bright = BrightDataClient(api_key=env_value('BRIGHTDATA_API_KEY'), unlocker_zone=env_value('BRIGHTDATA_UNLOCKER_ZONE'), client=transport, retries=0)

        async def one(pid, name, url):
            async with semaphore:
                try:
                    html = await bright.unlock(url)
                    parser = ImageMeta()
                    parser.feed(html)
                    if not parser.url:
                        outcomes['unavailable'] += 1
                        return
                    async with images.stream('GET', parser.url) as response:
                        response.raise_for_status()
                        body = bytearray()
                        async for chunk in response.aiter_bytes():
                            body.extend(chunk)
                            if len(body) > 5_000_000:
                                raise ValueError('oversized photo')
                    kind = image_format(bytes(body))
                    if not kind:
                        raise ValueError('unsupported image')
                    filename = hashlib.sha256(pid.encode()).hexdigest()[:24] + kind[0]
                    (CACHE / filename).write_bytes(body)
                    record = {'filename': filename, 'media_type': kind[1], 'source_url': url,
                              'provider': 'brightdata:web_unlocker', 'source_mode': 'live',
                              'collected_at': datetime.now(timezone.utc).isoformat()}
                    records[pid] = record
                    temporary = MANIFEST.with_suffix('.tmp')
                    temporary.write_text(json.dumps(records, indent=2))
                    temporary.replace(MANIFEST)
                    store.merge_node('Person', pid, {'photo_url': '/api/v1/connections/photos/' + filename,
                                                     'photo_source_url': url, 'photo_collected_at': record['collected_at'],
                                                     'photo_provider': record['provider']})
                    outcomes['saved'] += 1
                    print(f"Saved {name} ({outcomes['saved']})", flush=True)
                except Exception as exc:
                    outcomes['failed'] += 1
                    print(f'Photo unavailable for {name}: {type(exc).__name__}', flush=True)
        await asyncio.gather(*(one(*row) for row in targets))
    print(json.dumps({'attempted': len(targets), **outcomes, 'total_cached': len(records)}), flush=True)


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--name', action='append', help='Limit to an exact name; repeat for multiple people')
    args = parser.parse_args()
    asyncio.run(enrich(set(args.name) if args.name else None))
