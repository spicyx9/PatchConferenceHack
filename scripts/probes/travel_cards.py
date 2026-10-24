"""Read-only Bright Data catalogue audit; never starts a paid travel collection."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path

import httpx

from conferge.core.settings import env_value

ROOT = Path(__file__).resolve().parents[2]
DATASETS = {
    'Booking search': ('gd_m4bf7a917zfezv9d5', 'collect_by_url',
                       ['image', 'star_rating', 'review_score', 'review_count', 'bed_type',
                        'free_cancellation', 'no_prepayment', 'url']),
    'Booking details': ('gd_mdy9ld3p1e0oqlj9g4', 'collect_by_url',
                        ['images', 'most_popular_facilities', 'pricing', 'availability']),
    'Airbnb discovery': ('gd_ld7ll037kqy322v05', 'discover_by_location', ['url']),
    'Airbnb details': ('gd_ld7ll037kqy322v05', 'collect_by_url',
                       ['images', 'amenities', 'ratings', 'property_number_of_reviews',
                        'travel_details', 'total_price']),
    'Google Hotels discovery': ('gd_mg3gjfmg12tc2n5d4d', 'discover_by_search', ['url']),
    'Google Hotels details': ('gd_mg3gjfmg12tc2n5d4d', 'collect_by_url',
                             ['photos', 'star_classification', 'popular_amenities',
                              'booking_options', 'review_count']),
    'Google Flights details': ('gd_mhng7wen1rw0a3gvpf', 'collect_by_url',
                              ['legs', 'pricing', 'providers', 'search']),
}


async def main() -> int:
    lines = ['# Travel cards — Bright Data audit', '',
             f'Run at: {datetime.now(timezone.utc).isoformat()}', '',
             'Mode: public catalogue metadata only; no live offer collection.',
             f'BRIGHTDATA_API_KEY configured here: {bool(env_value("BRIGHTDATA_API_KEY"))}.', '',
             '| Source and method | Catalogue check |', '| --- | --- |']
    failed = False
    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
        for name, (dataset, method, fields) in DATASETS.items():
            url = f'https://docs.brightdata.com/scrapers/{dataset}.json'
            try:
                response = await client.get(url)
                response.raise_for_status()
                outputs = response.json()['collection_methods'][method]['output_fields']
                names = {f['name'] for f in outputs}
                missing = set(fields) - names
                status = 'Missing: ' + ', '.join(sorted(missing)) if missing else 'All expected top-level fields documented'
                failed |= bool(missing)
            except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
                status = 'Unverified: ' + type(exc).__name__
                failed = True
            lines.append(f'| [{name}: `{method}`]({url}) | {status} |')
    lines.extend(['', '## Findings and implemented changes', '',
        '- Booking search exposes image, stars, guest score/count, bed type and cancellation/prepayment flags. Detail collection exposes photos and facilities.',
        '- Airbnb and Google Hotels discovery document URL-only results. Collect those URLs before normalization; unmatched or failed details remain degraded and never invent stays.',
        '- Keep up to five property images and six facilities instead of dropping every Airbnb photo and amenity.',
        '- Flight leg logos/cabin labels and explicit baggage/price scope are retained when present. Nested flight fields are not described by the public catalogue: real-account response validation remains unverified.',
        '- Preserve presentation details alongside core-valid records in the cache. Older caches remain readable; missing historical images or stars stay unknown.',
        '- Explicit Bright Data Airbnb evidence distinguishes synchronous dataset responses from pyairbnb even without a snapshot id.',
        '- The UI keeps source collection badges and exact provider links; missing return itinerary, baggage and fees stay visible. Stars are never derived from guest reviews.',
        '- Local airline logos are static brand assets, not a travel-data fallback. Source-provided logos take precedence.', '',
        '## Verification limits', '',
        'Provider data-path tests use mocked responses. Browser checks use the committed cached offers and a separately labelled fictional example. No new live quote, production deployment or reservation was verified.',
        'Kayak blocked the automated result view and Booking did not render result cards in the reference browser. The layout follows the requested information hierarchy; no claim of a pixel-perfect captured copy.', '',
        'Browser test: `NODE_PATH=<Playwright modules> BASE_URL=http://127.0.0.1:8051 node tests/api/travel_cards_flow.cjs`.',
        'General checks: `make check`.', ''])
    destination = ROOT / 'probes' / 'travel_cards.md'
    destination.write_text('\n'.join(lines))
    print(f'Wrote {destination.relative_to(ROOT)}; catalogue {"needs attention" if failed else "verified"}; live travel collection not attempted')
    return int(failed)


if __name__ == '__main__':
    raise SystemExit(asyncio.run(main()))
