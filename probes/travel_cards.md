# Travel cards — Bright Data audit

Run at: 2026-10-24T21:27:02.860985+00:00

Mode: public catalogue metadata only; no live offer collection.
BRIGHTDATA_API_KEY configured here: False.

| Source and method | Catalogue check |
| --- | --- |
| [Booking search: `collect_by_url`](https://docs.brightdata.com/scrapers/gd_m4bf7a917zfezv9d5.json) | All expected top-level fields documented |
| [Booking details: `collect_by_url`](https://docs.brightdata.com/scrapers/gd_mdy9ld3p1e0oqlj9g4.json) | All expected top-level fields documented |
| [Airbnb discovery: `discover_by_location`](https://docs.brightdata.com/scrapers/gd_ld7ll037kqy322v05.json) | All expected top-level fields documented |
| [Airbnb details: `collect_by_url`](https://docs.brightdata.com/scrapers/gd_ld7ll037kqy322v05.json) | All expected top-level fields documented |
| [Google Hotels discovery: `discover_by_search`](https://docs.brightdata.com/scrapers/gd_mg3gjfmg12tc2n5d4d.json) | All expected top-level fields documented |
| [Google Hotels details: `collect_by_url`](https://docs.brightdata.com/scrapers/gd_mg3gjfmg12tc2n5d4d.json) | All expected top-level fields documented |
| [Google Flights details: `collect_by_url`](https://docs.brightdata.com/scrapers/gd_mhng7wen1rw0a3gvpf.json) | All expected top-level fields documented |

## Findings and implemented changes

- Booking search exposes image, stars, guest score/count, bed type and cancellation/prepayment flags. Detail collection exposes photos and facilities.
- Airbnb and Google Hotels discovery document URL-only results. Collect those URLs before normalization; unmatched or failed details remain degraded and never invent stays.
- Keep up to five property images and six facilities instead of dropping every Airbnb photo and amenity.
- Flight leg logos/cabin labels and explicit baggage/price scope are retained when present. Nested flight fields are not described by the public catalogue: real-account response validation remains unverified.
- Preserve presentation details alongside core-valid records in the cache. Older caches remain readable; missing historical images or stars stay unknown.
- Explicit Bright Data Airbnb evidence distinguishes synchronous dataset responses from pyairbnb even without a snapshot id.
- The UI keeps source collection badges and exact provider links; missing return itinerary, baggage and fees stay visible. Stars are never derived from guest reviews.
- Local airline logos are static brand assets, not a travel-data fallback. Source-provided logos take precedence.

## Verification limits

Provider data-path tests use mocked responses. Browser checks use the committed cached offers and a separately labelled fictional example. No new live quote, production deployment or reservation was verified.
Kayak blocked the automated result view and Booking did not render result cards in the reference browser. The layout follows the requested information hierarchy; no claim of a pixel-perfect captured copy.

Browser test: `NODE_PATH=<Playwright modules> BASE_URL=http://127.0.0.1:8051 node tests/api/travel_cards_flow.cjs`.
General checks: `make check`.
