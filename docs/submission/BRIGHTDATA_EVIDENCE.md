# Bright Data pitch — verify the numbers

One read-only command recomputes the figures shown on the Conferge comparison slide from **committed evidence**:

```bash
python scripts/verify_brightdata_pitch.py --check
python scripts/verify_brightdata_pitch.py --json
```

The command needs only Python 3 and local JSON files; it **does not make external requests, spend credits, edit a graph, or modify the running demo**. `--check` exits with a nonzero status if a captured slide figure differs from the source files.

## Sources and what they prove

| Claim on slide | Evidence in the repository | Interpretation |
|---|---|---|
| **8/16 direct access** | [`data/block_matrix.json`](../../data/block_matrix.json) | At least one ordinary HTTP request (default or browser user-agent) passed the file's semantic content-marker check. |
| **14/16 via Bright Data** | [`data/block_matrix.json`](../../data/block_matrix.json) | Web Unlocker or a Bright Data Dataset snapshot passed the check. |
| **+6 Bright-Data-only sources** | Same JSON; recomputed by the script | Facebook Events, Google Search, LinkedIn public profile, GitHub API, Booking, Hilton. |
| **34 captured flight observations; 20 JFK departures** | [`data/cache/flights.json`](../../data/cache/flights.json) | Web Unlocker / Google Flights capture. **Return slices missing for all 34; not 34 bookable round trips.** 13 start from EWR and 1 from LGA. |
| **15 Booking quotes and 6 Airbnb quotes** | [`data/cache/stays.json`](../../data/cache/stays.json) | Bright Data Dataset results with `quoted_total` price status. A quote is **not** an independently reconfirmed booking, taxes/fees may be uncertain. |
| **17 LinkedIn public profiles** | [`data/cache/linkedin_public.json`](../../data/cache/linkedin_public.json) | Cached profile records, not proof of conference attendance. |

## How 16 sites were selected

Original matrix: **21 sites**, captured **2026-10-24 19:01 UTC**. The slide intentionally excludes four Web Unlocker KYC-refused domains (`Kayak`, `Hotels.com`, `Expedia`, `Marriott`) and the `Luma discover API` because the latter is consumed directly. That leaves **16 tested endpoints**. The two endpoints unconfirmed by either of these particular access tests are the RainFocus *HTML shell* and `SerpApi Google Flights`; Conferge's RainFocus **separate public catalog API connector** should not be confused with the shell. Luma API data is not attributed to Bright Data.

All access results are results of these *specific attempts* and markers, not a claim that a vendor can or cannot access a domain in general.

## What this does *not* verify

The script checks **source records and counts**, not current prices, booking availability, independently confirmed people identities, or a fully like-for-like test of Claude and ChatGPT. Those comparisons require preserving each app's original answers and running the same timestamped field-level verifier on all three columns. Never present missing model outputs as zero verified.

All counted figures are historical captures for October 24, 2026. For reproducibility, use this repo commit and source files, not a new live query which may return different prices or content.