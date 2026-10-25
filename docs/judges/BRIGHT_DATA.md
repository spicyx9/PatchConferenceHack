# Bright Data: acquisition with evidence

Conferge uses Bright Data where ordinary requests are incomplete or blocked. It stores the result with provider, API, dataset/zone, source URL, snapshot ID, and collection time, then reasons over the saved record—never over an untraceable live fetch.

## What was captured

| Source | Bright Data route | Committed result | Boundary |
|---|---|---:|---|
| Google Flights | Web Unlocker | 34 outbound observations | Page-quoted totals; return slices were not collected and booking was not verified |
| Booking | Dataset snapshot `sd_mvmqn1ir1b96s56ixb` | 15 stays | A collected quote, not verified availability or a reservation |
| Airbnb | Dataset snapshot `sd_mvmqn1lb1iu27stdzv` | 6 stays | A collected quote, not verified availability or a reservation |
| LinkedIn | SERP URL discovery + profile dataset | 17 public profiles | Enrichment corroborates identity/company; it never proves attendance |
| Crunchbase | SERP URL discovery + dataset | 2 companies | Public company enrichment |
| Google Maps | Dataset | 15 raw rows, 9 requested venues, 4 matches | Raw rows are not all verified venue matches |

Run `uv run python scripts/verify_judge_evidence.py --check` to recompute the first four counts from [`data/cache`](../../data/cache).

## Why these pages are hard to get

Dynamic travel pages, anti-bot responses, and search-mediated identity resolution do not behave like stable JSON APIs. Conferge routes all Bright Data work through the shared, retrying client in [`conferge/core/brightdata.py`](../../conferge/core/brightdata.py): dataset trigger/snapshot reads, SERP requests, Web Unlocker requests, credential checks, and sanitized failures.

- Google Flights Web Unlocker parsing and explicit outbound-only semantics: [`conferge/flights/unlocker_provider.py`](../../conferge/flights/unlocker_provider.py)
- Booking dataset: [`conferge/lodging/booking.py`](../../conferge/lodging/booking.py)
- Airbnb dataset: [`conferge/lodging/airbnb.py`](../../conferge/lodging/airbnb.py)
- LinkedIn dataset enrichment: [`conferge/people/linkedin.py`](../../conferge/people/linkedin.py)
- Crunchbase SERP + dataset: [`conferge/people/crunchbase.py`](../../conferge/people/crunchbase.py)
- Event discovery through SERP: [`conferge/events/discovery/serp.py`](../../conferge/events/discovery/serp.py)

## Direct access versus Bright Data

The committed access experiment covers **21 sites**: **10** succeeded directly, **14** through Bright Data, **12** through Web Unlocker alone, and **16** through any attempted path. The verification script recalculates these figures from every site's two direct user-agent attempts, Web Unlocker attempt, and Dataset attempt in [`data/block_matrix.json`](../../data/block_matrix.json); it does not trust the file's aggregate counters.

The often-cited “8 of 16 direct versus 14 of 16 Bright Data” subset is intentionally not used: the evidence file does not define which five endpoints belong to that scope, so it cannot be reproduced honestly.

## Failure handling and provenance

Missing credentials, provider error records, timeouts, empty datasets, and incomplete snapshots remain explicit states. The Google Flights dataset and Google Hotels dataset produced no usable captured records; the 34 flight observations came from **Web Unlocker**, not the Flights dataset. Startup replays timestamped cache data and labels it `cached`; it does not imply live availability.

See [Verify the results](VERIFY.md) for exact commands.
