# Probe: Bright Data first, stays and flights

- run at: 2026-10-24T18:41:09.024871+00:00 (one run per site, 120 s cap per provider call)
- stays: San Francisco 2026-10-27 -> 2026-10-30, 2 adults, USD; flights: JFK/EWR/LGA -> SFO 2026-10-27 / 2026-10-30, 1 adult economy
- stays envelope: live/degraded, 21 stays; flights: 0 offers
- Bright Data usage in this run: {'datasets': 22, 'web_unlocker': 0, 'serp': 0, 'total': 22}
- resumed snapshots: {'gd_m4bf7a917zfezv9d5': 'sd_mvmqn1ir1b96s56ixb', 'gd_mg3gjfmg12tc2n5d4d': 'sd_mvmqn1k358049lk2z', 'gd_ld7ll037kqy322v05': 'sd_mvmqn1lb1iu27stdzv'}; skipped: ['flights', 'unlocker']

### Stays

| provider / API | records | priced | price status | min | max |
|---|---|---|---|---|---|
| Bright Data dataset gd_m4bf7a917zfezv9d5 (Booking) | 15 | 15 | quoted_total | 252.00 | 1213.00 |
| Bright Data dataset gd_ld7ll037kqy322v05 (Airbnb) | 6 | 6 | quoted_total | 647.00 | 791.12 |

Provider reports:

- `booking` : degraded/page_cap, fetched 15; errors: none
- `google_hotels` : degraded/error, fetched 0; errors: none
- `airbnb` : ok/exhausted, fetched 6; errors: none

### Flights (single runs earlier on 2026-10-24, not repeated to spare credits)

| provider / API | records | priced | price status | min | max |
|---|---|---|---|---|---|
| Bright Data dataset gd_mhng7wen1rw0a3gvpf (Google Flights) | 0 | 0 | - | - | - |
| Bright Data Web Unlocker web_unlocker1 (Google Flights) | 34 | 0 as total_price | unknown (RT total kept in raw_price_text) | 413 (observed RT total) | 841 (observed RT total) |
| Bright Data Web Unlocker web_unlocker1 (Kayak) | 0 | 0 | - | - | - |
| Fallback fast-flights | 36 | 36 | observed_live (one way) | 333 | - |

- Dataset: snapshots sd_mvmqn1kd1ty930z4jj, sd_mvmqn1l21499xs75pl and sd_mvmqn23o2mnatsrk8y (JFK, EWR, LGA) were still `running` after 396 s, past the 120 s cap.
- Web Unlocker Google Flights: 1 page for the three NYC airports, every segment with a flight number. The page lists outbound legs with the round-trip total, so the offers stay `one_way` with `total_price=None`.
- Kayak: Bright Data refuses it ("Residential Failed (bad_endpoint)", KYC required).
- fast-flights (probe at 18:07 UTC): 36 one-way offers; the cheapest outbound is $333 (JFK-BOS-SFO) and the cheapest return $345.

### Stays via Web Unlocker (single run at 18:2x UTC, not repeated)

| provider / API | records | priced | price status | min | max |
|---|---|---|---|---|---|
| Bright Data Web Unlocker web_unlocker1 (Hilton) | 20 | 0 | unknown (dated rates load client-side) | - | - |
| Bright Data Web Unlocker (Kayak, Hotels.com, Expedia, Marriott) | 0 | 0 | refused: KYC required | - | - |


## Shown in the demo (integration pick)

- stay: Chelsea Inn | Bright Data dataset gd_m4bf7a917zfezv9d5 (Booking) | quoted_total | 500.00 USD
- stay: La Luna Inn, an Ascend Collection Hotel | Bright Data dataset gd_m4bf7a917zfezv9d5 (Booking) | quoted_total | 564.00 USD
- stay: Nob Hill Motor Inn | Bright Data dataset gd_m4bf7a917zfezv9d5 (Booking) | quoted_total | 501.00 USD
- stay: San Remo Hotel | Bright Data dataset gd_m4bf7a917zfezv9d5 (Booking) | quoted_total | 323.00 USD
- stay: Holiday Inn San Francisco - Golden Gateway newly renovated with No Resort Fee | Bright Data dataset gd_m4bf7a917zfezv9d5 (Booking) | quoted_total | 1213.00 USD
- stay: Hotel Majestic | Bright Data dataset gd_m4bf7a917zfezv9d5 (Booking) | quoted_total | 689.00 USD

Prices are what each source showed at collection time; nothing is estimated. Raw envelopes: raw/travel/ (gitignored).
