# Resilience findings (2026-10-24)

Suite: `tests/resilience/`, run against the real app (`create_app`) and real providers. Failures
come from real sockets: a closed FalkorDB port, a local HTTP server answering 429 or too slowly,
a missing `BRIGHTDATA_API_KEY`. No code is mocked. Tests that need the public internet (Airbnb,
Google Flights) run only with `CONFERGE_LIVE_TESTS=1`.

| # | Case | Verdict | Test |
|---|---|---|---|
| 1 | FalkorDB down (closed port) | pass | `test_resilience_1_falkordb_down.py` |
| 2 | No Bright Data key | pass (offline fixture fallback; live Airbnb/fast-flights fallback with `CONFERGE_LIVE_TESTS=1`) | `test_resilience_2_missing_brightdata_key.py` |
| 3 | Scraper timeout 0.1 s | pass | `test_resilience_3_scraper_timeout.py` |
| 4 | Stay / flight without a price | pass on the invariant (null, never 0, never estimated); status value differs from the brief, see F1 | `test_resilience_4_missing_price.py` |
| 5 | In-person event in another timezone | pass | `test_resilience_5_other_timezone.py` |
| 6 | Bright Data 429 | pass: 3 requests per call (first attempt + 2 retries), then fallback | `test_resilience_6_brightdata_429.py` |

No test failed, so no fix was made in `conferge/lodging`, `conferge/flights`,
`conferge/core/brightdata.py` or `conferge/integration`. The findings below are outside the
paths this pass may change, or are observations, not failures.

## F1. A missing price is `unknown`, not `unavailable` (contract decision, window 0)

- `conferge/lodging/normalize.py:68`: `decide_price_status` returns `unknown` when no price was
  collected, and `unavailable` only when the room itself is unavailable
  (`availability == "unavailable"`). This follows `docs/CONTRACTS.md:33` ("unknown charges
  remain unknown"). Switching to `unavailable` would conflate "price not collected" with "not
  bookable" and change the lodging ranking (`PRICE_STATUS_RANK`).
- `conferge/core/schemas.py:301`: `FlightOffer.price_status` has no `unavailable` value; a missing
  fare is `unknown` (with the `price_missing` warning). Adding `unavailable` is a schema change
  for window 0.
- What the test enforces: `total_price`, `nightly_avg`, `base_total`, `taxes` and `fees_total`
  are null; the status is `unknown` or `unavailable`; `/api/v1/travel` budget fields and
  `remaining_usd` are null. 12 of the 15 fixture stays are priced normally and none of them is
  priced once its price fields are removed.

## F2. The offline `no_network` guard cannot block curl_cffi (tests)

- `tests/integration/conftest.py:15-17` patches Python `socket` only. pyairbnb uses curl_cffi
  (libcurl, native sockets), so an offline test that reaches `collect_stays_flights` really calls
  Airbnb. This was hit in PR #18. The e2e tests now stub live travel explicitly.

## F3. Retry-After is not honoured (observation)

- `conferge/core/brightdata.py:89-90`: a 429 is retried after a fixed 1 s, then 2 s backoff,
  whatever `Retry-After` says. The retry bound (2) holds, as the test checks. Honouring
  `Retry-After` (capped) would be kinder to the quota. This is not needed for correctness.

## F4. A timed-out thread keeps running (observation)

- `conferge/flights/fastflights_provider.py:117,120` and `conferge/lodging/airbnb.py:182` wrap
  synchronous libraries in `asyncio.to_thread`. On timeout the coroutine is cancelled and
  reported `failed`, but the worker thread runs until the library returns, and `asyncio.run`
  waits for it at shutdown. The fallback is clean; only the process exit can be delayed.
