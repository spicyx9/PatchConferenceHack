# Probe: lodging (window 05)

- run at: 2026-10-24T16:42:48.912787+00:00
- query: Fort Mason Center (37.8060, -122.4320), radius 3 km, check-in 2026-10-27, check-out 2026-10-30 (3 nights), 1 adult, 1 room, USD, country us, limit 5 per input
- BRIGHTDATA_API_KEY present: False | pyairbnb importable: True
- envelope: **source_mode live**, status **degraded**, 5 stays, 0 cross-provider dedup groups
- price_status counts: verified_bookable 0, quoted_total 5, indicative 0, unknown 0, unavailable 0
- rule: `verified_bookable` only with a dated detail re-check < 30 min, verified availability, all-fees total and deeplink; Airbnb and Google Hotels never reach it (taxes not exposed / metasearch).

## Providers

### booking

- **state: missing_credentials** | source_mode: **live** | fetched 0 | unique 0 | pages 0 | expected None
- errors: ['missing_credentials: BRIGHTDATA_API_KEY']
- warnings: none

### google_hotels

- **state: missing_credentials** | source_mode: **live** | fetched 0 | unique 0 | pages 0 | expected None
- errors: ['missing_credentials: BRIGHTDATA_API_KEY']
- warnings: none

### airbnb

- **state: ok/exhausted** | source_mode: **live** | fetched 280 | unique 238 | pages 0 | expected None
- errors: none
- warnings: ['pyairbnb: 42 duplicate listing(s) merged', 'pyairbnb: kept 5 of 238 unique listings (query limit)']
- verification: ok/not_applicable | fetched 5 | errors none
- raw saved (gitignored): `raw/lodging/airbnb-20261024T164259Z.json`

Fields of the first raw row (airbnb, live):

| field | type | example |
|---|---|---|
| `room_id` | int | 1681202053543469883 |
| `category` | str | "" |
| `structuredContent` | dict | {"__typename": "ExploreStructuredContent", "distance": [], "mapCategoryInfo": null, "mapPr |
| `passportData` | dict | {} |
| `paymentMessages` | list | [{"__typename": "PaymentMessage", "text": "+$136 Airbnb credit", "type": "HOTEL_CREDIT_HIG |
| `kind` | str | "" |
| `name` | str | "Hotel Zoe Fisherman's Wharf, Deluxe two queen room" |
| `title` | str | "Hotel Zoe Fisherman's Wharf" |
| `type` | str | "" |
| `long_stay_discount` | dict | {} |
| `fee` | dict | {"airbnb": {}, "cleaning": {}} |
| `price` | dict | {"unit": {"qualifier": ""}, "total": {"currency_symbol": "", "amount": 0}, "break_down": [ |
| `rating` | dict | {"value": 4.64, "reviewCount": "180"} |
| `images` | list | [{"url": "https://a0.muscache.com/im/pictures/BnbProperty/BnbProperty-1690603304113941536/ |
| `badges` | list | ["FEATURED_HOTEL"] |
| `coordinates` | dict | {"latitude": 37.8062, "longitud": -122.4142} |

### airbnb_brightdata_only

- **state: missing_credentials** | source_mode: **live** | fetched 0 | unique 0 | pages 0 | expected None
- errors: ['missing_credentials: BRIGHTDATA_API_KEY not set']
- warnings: none

## Normalized stays (live)

| provider | name | price_status | total | nightly_avg | taxes | fees | all fees? | availability | m to Fort Mason | walk min (est.) | mode | collected_at | link |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| airbnb | Cow Hollow Inn, Deluxe double room with two doub | quoted_total | 792.00 USD | 264.00 | None | None | None | verified_available | 833 | 10 | live | 2026-10-24T16:42:55.813212+00:00 | https://www.airbnb.com/rooms/1097972701874435919?check_in=2026-10-27&check_out=2026-10-30&adults=1&currency=USD |
| airbnb | Signature Inn Marina, 1 King bed | quoted_total | 617.00 USD | 205.67 | None | None | None | verified_available | 1117 | 14 | live | 2026-10-24T16:42:55.813212+00:00 | https://www.airbnb.com/rooms/1686487891667178739?check_in=2026-10-27&check_out=2026-10-30&adults=1&currency=USD |
| airbnb | Hotel Zoe Fisherman's Wharf, Deluxe two queen ro | quoted_total | 1034.00 USD | 344.67 | None | 123.60 | None | verified_available | 1564 | 19 | live | 2026-10-24T16:42:55.813212+00:00 | https://www.airbnb.com/rooms/1681202053543469883?check_in=2026-10-27&check_out=2026-10-30&adults=1&currency=USD |
| airbnb | Hotel Nikko, Queen Room | quoted_total | 1741.71 USD | 580.57 | None | 137.76 | None | verified_available | 2987 | 36 | live | 2026-10-24T16:42:55.813212+00:00 | https://www.airbnb.com/rooms/1110849551263993639?check_in=2026-10-27&check_out=2026-10-30&adults=1&currency=USD |
| airbnb | The Mosser, Deluxe queen | quoted_total | 430.95 USD | 143.65 | None | None | None | verified_available | 3307 | 40 | live | 2026-10-24T16:42:55.813212+00:00 | https://www.airbnb.com/rooms/1102891445409567406?check_in=2026-10-27&check_out=2026-10-30&adults=1&currency=USD |

Normalization warnings:

- airbnb:1681202053543469883: get_price without nights qualifier; ignored
- airbnb:1686487891667178739: get_price without nights qualifier; ignored
- airbnb:1097972701874435919: get_price without nights qualifier; ignored
- airbnb:1102891445409567406: get_price without nights qualifier; ignored
- airbnb:1110849551263993639: get_price without nights qualifier; ignored

## FIXTURE (labelled, not live): fixtures/lodging.json

- 15 stays, source_mode **fixture**; Booking and Google Hotels rows are fictional (no key), Airbnb rows are a trimmed real pyairbnb capture, all marked fixture.

| provider | name | price_status | total | nightly_avg | taxes | fees | all fees? | availability | m to Fort Mason | walk min (est.) | mode | collected_at | link |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| booking | Fort Mason Guest House (fictional fixture) | quoted_total | 1488.00 USD | 496.00 | None | None | True | unknown | 255 | None | fixture | 2026-10-24T16:33:00+00:00 | https://www.booking.com/hotel/us/fixture-fort-mason-guest-house.html?checkin=2026-10-27&checkout=2026-10-30&group_adults=1&no_rooms=1&group_children=0&selected_currency=USD&sb_price_type=total |
| google_hotels | Marina Bay Inn (fictional fixture) | quoted_total | 905.00 USD | 301.67 | None | None | None | unknown | 574 | None | fixture | 2026-10-24T16:33:00+00:00 | https://www.example.com/fixture-ota-a/marina-bay-inn |
| booking | Marina Bay Inn (fictional fixture) | quoted_total | 912.00 USD | 304.00 | None | None | None | unknown | 587 | None | fixture | 2026-10-24T16:33:00+00:00 | https://www.booking.com/hotel/us/fixture-marina-bay-inn.html?checkin=2026-10-27&checkout=2026-10-30&group_adults=1&no_rooms=1&group_children=0&selected_currency=USD&sb_price_type=total |
| booking | Chestnut Street Hotel (fictional fixture) | quoted_total | 1104.00 USD | 368.00 | None | 162.00 | False | unknown | 681 | None | fixture | 2026-10-24T16:33:00+00:00 | https://www.booking.com/hotel/us/fixture-chestnut-street-hotel.html?checkin=2026-10-27&checkout=2026-10-30&group_adults=1&no_rooms=1&group_children=0&selected_currency=USD&sb_price_type=total |
| booking | Lombard Motor Lodge (fictional fixture) | quoted_total | 640.00 USD | 213.33 | None | None | None | unknown | 728 | None | fixture | 2026-10-24T16:33:00+00:00 | https://www.booking.com/hotel/us/fixture-lombard-motor-lodge.html?checkin=2026-10-27&checkout=2026-10-30&group_adults=1&no_rooms=1&group_children=0&selected_currency=USD&sb_price_type=total |
| booking | Van Ness Tower Hotel (fictional fixture) | quoted_total | 1215.00 USD | 405.00 | None | None | None | unknown | 1049 | None | fixture | 2026-10-24T16:33:00+00:00 | https://www.booking.com/hotel/us/fixture-van-ness-tower.html?checkin=2026-10-27&checkout=2026-10-30&group_adults=1&no_rooms=1&group_children=0&selected_currency=USD&sb_price_type=total |
| booking | North Beach Pier Hotel (fictional fixture) | quoted_total | 1402.00 USD | 467.33 | None | None | True | verified_available | 1319 | None | fixture | 2026-10-24T16:33:00+00:00 | https://www.booking.com/hotel/us/fixture-north-beach-pier-hotel.html?checkin=2026-10-27&checkout=2026-10-30&group_adults=1&no_rooms=1&group_children=0&selected_currency=USD&sb_price_type=total |
| google_hotels | Presidio Gate Hotel (fictional fixture) | quoted_total | 1180.00 USD | 393.33 | None | None | None | unknown | 1560 | None | fixture | 2026-10-24T16:33:00+00:00 | https://www.example.com/fixture-ota-a/presidio-gate |
| airbnb | Hotel Zoe Fisherman's Wharf, Deluxe king room | quoted_total | 1022.00 USD | 340.67 | None | 123.60 | None | unknown | 1564 | None | fixture | 2026-10-24T16:33:00+00:00 | https://www.airbnb.com/rooms/1681202052912791908?check_in=2026-10-27&check_out=2026-10-30&adults=1&currency=USD |
| airbnb | Female 4 Bed Dormitory at Social SF Hostel | quoted_total | 147.00 USD | 49.00 | None | None | None | unknown | 2509 | None | fixture | 2026-10-24T16:33:00+00:00 | https://www.airbnb.com/rooms/4464347?check_in=2026-10-27&check_out=2026-10-30&adults=1&currency=USD |
| airbnb | The Mosser, Deluxe queen | quoted_total | 430.95 USD | 143.65 | None | None | None | unknown | 3307 | None | fixture | 2026-10-24T16:33:00+00:00 | https://www.airbnb.com/rooms/1102891445409567406?check_in=2026-10-27&check_out=2026-10-30&adults=1&currency=USD |
| google_hotels | Aquatic Park Lodge (fictional fixture) | indicative | None USD | 289.00 | None | None | None | unknown | 923 | None | fixture | 2026-10-24T16:33:00+00:00 | https://www.example.com/fixture-ota-c/aquatic-park |
| booking | Cow Hollow Suites (fictional fixture) | unknown | None  | None | None | None | None | unknown | 1025 | None | fixture | 2026-10-24T16:33:00+00:00 | https://www.booking.com/hotel/us/fixture-cow-hollow-suites.html?checkin=2026-10-27&checkout=2026-10-30&group_adults=1&no_rooms=1&group_children=0&selected_currency=USD&sb_price_type=total |
| google_hotels | Russian Hill Boutique (fictional fixture) | unknown | None  | None | None | None | None | unknown | 1231 | None | fixture | 2026-10-24T16:33:00+00:00 | https://www.google.com/travel/hotels/entity/fixture-gh-4 |
| booking | Pacific Heights Hotel (fictional fixture) | unavailable | 990.00 USD | 330.00 | None | None | None | unavailable | 1567 | None | fixture | 2026-10-24T16:33:00+00:00 | https://www.booking.com/hotel/us/fixture-pacific-heights-hotel.html?checkin=2026-10-27&checkout=2026-10-30&group_adults=1&no_rooms=1&group_children=0&selected_currency=USD&sb_price_type=total |
