# conferge/flights (window 06)

Entry point: `await conferge.flights.service.run({"origin_city", "destination_city", "departure_date", "return_date", "adults", "cabin"})` returns `DataEnvelope[FlightOffer]`. Proposals for w11: `conferge.flights.proposals.propose_alternatives`.

| Module | Role |
|---|---|
| `airports.py` | city to IATA expansion (primary / secondary), IATA to IANA table |
| `brightdata_provider.py` | `Source` for dataset `gd_mhng7wen1rw0a3gvpf`: discover_by=input_filters (candidate URLs), collect_by_url, record mapping |
| `fastflights_provider.py` | public Google Flights page via fast-flights (optional package), two one-way searches |
| `serpapi_provider.py` | SerpApi round trip (outbound, then `departure_token` for the return), `no_cache=true` |
| `normalize.py` | provider-neutral `RawOffer` to `FlightOffer` |
| `dedupe.py` | itinerary id from physical segments; price never part of identity |
| `service.py` | airport fan-out, router, 20 min cache, explicit fixture opt-in |
| `proposals.py` | depart J-1 / return J+1 if cheaper by more than 80 USD or event the day before |

## Decisions (2026-10-24)

1. Router per airport pair: Bright Data, then fast-flights, then SerpApi; the next provider runs when the previous fails, returns nothing, or returns no priced offer. The envelope is `degraded` as soon as one provider failed.
2. Default airports: NYC = JFK, LGA, EWR; SF = SFO, OAK. SJC is secondary (about 75 min by road from Fort Mason) and only searched with `include_secondary=True`. 6 pairs by default, 9 with SJC.
3. Bright Data inputs use Google labels (`"Round trip"`, `"Economy"`): a third party reports the live validator rejects the documented snake_case values. To confirm with the first keyed call.
4. Bright Data legs give local clock strings without date or AM/PM. Times are only set when one reading is consistent with the leg date, the reported travel time and (when no AM/PM) a 24 h clock proved by the record itself (an hour 13..23 or 0). Otherwise `None` with a `time_unresolved` warning.
5. fast-flights round-trip pages list outbound options only, without flight numbers. Rather than invent a return slice, the provider runs two one-way searches and returns `one_way` offers. Proposals then compare cheapest outbound plus cheapest return, flagged `sum_of_two_one_way_fares`.
6. Offers without a flight number get an unmergeable itinerary key: they are never merged with another source.
7. A `booking_token` is never stored in `booking_url`; only http(s) URLs are accepted, classified `google_flights_booking` (tfs booking URL) or `google_flights_search`.
8. Fixture `fixtures/flights.json` is FICTIONAL (carrier ZZ), `price_status=unknown`, fixture evidence, only returned with `allow_fixture=True`.
9. Bright Data decision rule: if `legs` and `pricing` come back empty from collect_by_url, fast-flights through the Bright Data SERP zone becomes primary (Bright Data as transport).
