# Probe: flights (w06)

Query: JFK -> SFO, 2026-10-27 / 2026-10-30, 1 adult, economy. Run at 2026-10-24T16:41:20.182027+00:00.

Prices are Google Flights metasearch observations (`observed_live`), never ticket guarantees. Baggage unknown unless stated. No fixture is relabelled.

## Bright Data Google Flights `gd_mhng7wen1rw0a3gvpf`

- probe verdict: **missing_credentials**
- mode: **live (attempted)**
- status / termination: `failed` / `error`
- fetched (raw) / unique: 0 / 0; normalized offers: 0
- window: 2026-10-24T16:41:20.204263+00:00 -> 2026-10-24T16:41:20.204277+00:00
- error: Bright Data key missing; set BRIGHTDATA_API_KEY

## fast-flights (public Google Flights page)

- probe verdict: **ok**
- mode: **live (attempted)**
- status / termination: `ok` / `exhausted`
- fetched (raw) / unique: 215 / 128; normalized offers: 128
- window: 2026-10-24T16:41:20.218190+00:00 -> 2026-10-24T16:41:22.801654+00:00
- raw (git-ignored): `probes/raw/flights-fastflights-20261024T164122Z.json`
- trip types: {'one_way': 128}; priced: 128/128
- completeness: segments with flight number 0/223, with timezone-aware departure 223/223
- itineraries (dedup groups): 128
- collected_at: 2026-10-24T16:41:22.792301+00:00
- source: https://www.google.com/travel/flights/search?tfs=GhoSCjIwMjYtMTAtMjdqBRIDSkZLcgUSA1NGT0IBAUgBmAEC&tfu=EgQIABABIgA&hl=en-US&curr=USD
- source: https://www.google.com/travel/flights/search?tfs=GhoSCjIwMjYtMTAtMzBqBRIDU0ZPcgUSA0pGS0IBAUgBmAEC&tfu=EgQIABABIgA&hl=en-US&curr=USD

Cheapest samples:

- `one_way` 333 USD (observed_live): B6 JFK 2026-10-27T15:14:00-04:00 -> BOS 2026-10-27T16:59:00-04:00; B6 BOS 2026-10-27T20:40:00-04:00 -> SFO 2026-10-28T00:25:00-07:00
- `one_way` 333 USD (observed_live): B6 JFK 2026-10-27T17:48:00-04:00 -> BOS 2026-10-27T19:41:00-04:00; B6 BOS 2026-10-27T20:40:00-04:00 -> SFO 2026-10-28T00:25:00-07:00
- `one_way` 345 USD (observed_live): B6 SFO 2026-10-30T23:25:00-07:00 -> FLL 2026-10-31T07:45:00-04:00; B6 FLL 2026-10-31T10:50:00-04:00 -> JFK 2026-10-31T13:41:00-04:00
- `one_way` 372 USD (observed_live): DL JFK 2026-10-27T15:59:00-04:00 -> SFO 2026-10-27T19:32:00-07:00
- warning: round_trip_as_two_one_way: Google lists only outbound options for a round-trip query; offers are one-way fares, not a combined round trip
- warning: fast_flights_direct: no Bright Data integration configured

## SerpApi google_flights (no_cache=true)

- probe verdict: **missing_credentials**
- mode: **live (attempted)**
- status / termination: `failed` / `error`
- fetched (raw) / unique: 0 / 0; normalized offers: 0
- window: 2026-10-24T16:41:22.805082+00:00 -> 2026-10-24T16:41:22.805084+00:00
- error: SERPAPI_KEY missing

## Fixture `fixtures/flights.json`

- mode: **fixture** (explicitly loaded by the probe; FICTIONAL carrier ZZ)
- offers: 6; price_status: ['unknown']; evidence modes: ['fixture']

## Verdict

- live sources with data: fast-flights
- Bright Data decision rule: if `legs` and `pricing` come back empty from collect_by_url, fast-flights through the Bright Data SERP zone becomes primary (Bright Data as transport).
