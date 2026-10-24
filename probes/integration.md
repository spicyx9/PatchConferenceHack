# Probe: integration (window 15), fixture E2E

- run at: 2026-10-24T07:44:03.072984+00:00
- mode: **fixture** | assembled data_mode: **fixture**
- E2E verdict: **PASS** (WARN stages are documented gaps, not failures)

## Stages

| stage | outcome | detail |
|---|---|---|
| inventory | WARN | 12/17 components merged; not merged: w05 lodging, w06 flights, w07 people, w09 planner, w09 networking |
| sources | WARN | official=466 fixture/ok, luma=12 fixture/ok, partiful=6 fixture/degraded, eventbrite=8 fixture/degraded, aggregators=20 fixture/degraded, discovery=0 fixture/ok |
| check:provenance | PASS | 512 records, 0 without full source_mode/collected_at |
| check:labels | PASS | 6 slices checked |
| check:relations | PASS | candidate=20, confirmed_side_event=19, official=142, unknown=26 |
| check:dedup | PASS | 207 events, 183 people kept; 0 duplicates dropped (first record kept, none merged) |
| planning | PASS | demo-planner (w13): ok, 10 opportunities, source_mode=fixture; antifomo (merged): ok, 12 opportunities, source_mode=fixture; replanner (merged): ok, 12 opportunities, source_mode=fixture |
| graph | WARN | 648 nodes, 2146 edges via GraphStore; 49 skipped, 0 dangling |
| travel | PASS | 4 route plans, 9 legs, all fixture-labelled; 14 map features |
| api | PASS | 19 calls, 0 problems |
| demo-backup:w13-replay | PASS | deterministic offline replay of fixtures/demo.json |
| demo-backup:api-fixture | PASS | 19 calls, 0 problems |

## Sources

| source | window | path | source_mode | status | events | people | companies | collected_at | errors |
|---|---|---|---|---|---|---|---|---|---|
| official | w03 | fixture | fixture | ok | 161 | 183 | 122 | 2026-10-24T07:44:03.197925+00:00 | none |
| luma | w01 | fixture | fixture | ok | 12 | 0 | 0 | 2026-10-24T06:29:34.196299+00:00 | none |
| partiful | w01 | fixture | fixture | degraded | 6 | 0 | 0 | 2026-10-24T06:29:17.108007+00:00 | none |
| eventbrite | w02 | fixture | fixture | degraded | 8 | 0 | 0 | 2026-10-24T06:37:44.091146+00:00 | none |
| aggregators | w02 | fixture | fixture | degraded | 20 | 0 | 0 | 2026-10-24T06:38:25.662778+00:00 | none |
| discovery | w04 | fixture | fixture | ok | 0 | 0 | 0 | 2026-10-24T07:44:03.202454+00:00 | none |

## Components on main

| window | component | merged | contract | fixture | probe | issues |
|---|---|---|---|---|---|---|
| w01 | luma | yes | yes | yes | yes | conferge.events.luma |
| w01 | partiful | yes | yes | yes | yes | conferge.events.partiful |
| w02 | eventbrite | yes | yes | yes | yes | conferge.events.eventbrite |
| w02 | aggregators | yes | yes | yes | yes | conferge.events.aggregators |
| w03 | official | yes | yes | yes | yes | conferge.events.official |
| w04 | discovery | yes | yes | yes | yes | conferge.events.discovery |
| w05 | lodging | no | n/a | no | no | not merged on main yet |
| w06 | flights | no | n/a | no | no | not merged on main yet |
| w07 | people | no | n/a | no | no | not merged on main yet |
| w08 | graph | yes | yes | yes | yes | conferge.graph |
| w09 | planner | no | n/a | no | no | not merged on main yet |
| w09 | networking | no | n/a | n/a | n/a | not merged on main yet |
| w10 | antifomo | yes | yes | yes | yes | conferge.agents.antifomo |
| w10 | replanner | yes | yes | n/a | n/a | conferge.agents.replanner |
| w11 | travel | yes | yes | yes | yes | conferge.travel.routes |
| w12 | api | yes | yes | yes | yes | conferge.api.app |
| w13 | demo | yes | yes | yes | yes | conferge.demo |

## Interface mismatches for window 00

- fixture loaders are not uniform: aggregators.load_fixture_records, discovery.load_fixture, eventbrite.load_fixture_records, luma.load_fixture, official.load_fixture, partiful.load_fixture (load_fixture returns DiscoveryResult/OfficialCollection, load_fixture_records returns list[SourceRecord] without RunReport)
- conference id mismatch: API fixture uses 'conf-github-universe-2026', assembled data uses 'github-universe-2026'
- graph ingest skipped 49 edges: HOSTS: organizer not ingested

## Findings by stage

### graph
- skipped edges: HOSTS: organizer not ingested x49

## Graph shape (in-memory GraphStore run)

- nodes: {'Company': 122, 'Conference': 1, 'Event': 207, 'FlightOffer': 1, 'Goal': 3, 'Lodging': 2, 'Opportunity': 10, 'Person': 183, 'Topic': 54, 'Venue': 65}
- edges: {'ABOUT': 1259, 'EXHIBITS_AT': 54, 'INVOLVES': 30, 'LOCATED_AT': 200, 'PART_OF': 181, 'SERVES_GOAL': 10, 'SPEAKS_AT': 229, 'WORKS_AT': 183}

## Labels

- `fixture` rows come from each window's explicit, labelled loader; never shown as live.
- Lodging and flights: windows 05/06 not merged, the API fixture (fictional, labelled) is used and the domain is reported `fixture/degraded`.
- A failed live source stays `failed` with zero records unless `--fallback-fixture` was passed; the replacement slice is then listed separately as `fixture`.


---

# Live E2E (public endpoints, no API keys)

- run at: 2026-10-24T07:44:06.113012+00:00
- mode: **live** | assembled data_mode: **live**
- E2E verdict: **PASS** (WARN stages are documented gaps, not failures)

## Stages

| stage | outcome | detail |
|---|---|---|
| inventory | WARN | 12/17 components merged; not merged: w05 lodging, w06 flights, w07 people, w09 planner, w09 networking |
| sources | WARN | official=466 live/ok, luma=194 live/ok, partiful=11 live/degraded, eventbrite=19 live/ok, aggregators=7 live/ok, discovery=0 live/failed |
| check:provenance | PASS | 697 records, 0 without full source_mode/collected_at |
| check:labels | PASS | 6 slices checked |
| check:relations | PASS | candidate=7, confirmed_side_event=19, official=142, unknown=224 |
| check:dedup | PASS | 392 events, 183 people kept; 0 duplicates dropped (first record kept, none merged) |
| planning | PASS | demo-planner (w13): ok, 10 opportunities, source_mode=live; antifomo (merged): ok, 12 opportunities, source_mode=live; replanner (merged): ok, 12 opportunities, source_mode=live |
| graph | WARN | 927 nodes, 2316 edges via GraphStore; 622 skipped, 0 dangling |
| travel | PASS | 4 route plans, 9 legs, all fixture-labelled; 14 map features |
| api | PASS | 19 calls, 0 problems |

## Sources

| source | window | path | source_mode | status | events | people | companies | collected_at | errors |
|---|---|---|---|---|---|---|---|---|---|
| official | w03 | live | live | ok | 161 | 183 | 122 | 2026-10-24T07:44:08.720519+00:00 | none |
| luma | w01 | live | live | ok | 194 | 0 | 0 | 2026-10-24T07:44:17.751093+00:00 | none |
| partiful | w01 | live | live | degraded | 11 | 0 | 0 | 2026-10-24T07:44:06.540144+00:00 | none |
| eventbrite | w02 | live | live | ok | 19 | 0 | 0 | 2026-10-24T07:44:51.344404+00:00 | none |
| aggregators | w02 | live | live | ok | 7 | 0 | 0 | 2026-10-24T07:44:06.217641+00:00 | none |
| discovery | w04 | live | live | failed | 0 | 0 | 0 | 2026-10-24T07:44:06.141522+00:00 | Bright Data key missing; set BRIGHTDATA_API_KEY |

## Components on main

| window | component | merged | contract | fixture | probe | issues |
|---|---|---|---|---|---|---|
| w01 | luma | yes | yes | yes | yes | conferge.events.luma |
| w01 | partiful | yes | yes | yes | yes | conferge.events.partiful |
| w02 | eventbrite | yes | yes | yes | yes | conferge.events.eventbrite |
| w02 | aggregators | yes | yes | yes | yes | conferge.events.aggregators |
| w03 | official | yes | yes | yes | yes | conferge.events.official |
| w04 | discovery | yes | yes | yes | yes | conferge.events.discovery |
| w05 | lodging | no | n/a | no | no | not merged on main yet |
| w06 | flights | no | n/a | no | no | not merged on main yet |
| w07 | people | no | n/a | no | no | not merged on main yet |
| w08 | graph | yes | yes | yes | yes | conferge.graph |
| w09 | planner | no | n/a | no | no | not merged on main yet |
| w09 | networking | no | n/a | n/a | n/a | not merged on main yet |
| w10 | antifomo | yes | yes | yes | yes | conferge.agents.antifomo |
| w10 | replanner | yes | yes | n/a | n/a | conferge.agents.replanner |
| w11 | travel | yes | yes | yes | yes | conferge.travel.routes |
| w12 | api | yes | yes | yes | yes | conferge.api.app |
| w13 | demo | yes | yes | yes | yes | conferge.demo |

## Interface mismatches for window 00

- fixture loaders are not uniform: aggregators.load_fixture_records, discovery.load_fixture, eventbrite.load_fixture_records, luma.load_fixture, official.load_fixture, partiful.load_fixture (load_fixture returns DiscoveryResult/OfficialCollection, load_fixture_records returns list[SourceRecord] without RunReport)
- conference id mismatch: API fixture uses 'conf-github-universe-2026', assembled data uses 'github-universe-2026'
- graph ingest skipped 622 edges: HOSTS: organizer not ingested

## Findings by stage

### sources
- discovery [live]: Bright Data key missing; set BRIGHTDATA_API_KEY

### graph
- skipped edges: HOSTS: organizer not ingested x622

## Graph shape (in-memory GraphStore run)

- nodes: {'Company': 122, 'Conference': 1, 'Event': 392, 'FlightOffer': 1, 'Goal': 3, 'Lodging': 2, 'Opportunity': 10, 'Person': 183, 'Topic': 60, 'Venue': 153}
- edges: {'ABOUT': 1335, 'EXHIBITS_AT': 54, 'INVOLVES': 30, 'LOCATED_AT': 307, 'PART_OF': 168, 'SERVES_GOAL': 10, 'SPEAKS_AT': 229, 'WORKS_AT': 183}

## Labels

- `fixture` rows come from each window's explicit, labelled loader; never shown as live.
- Lodging and flights: windows 05/06 not merged, the API fixture (fictional, labelled) is used and the domain is reported `fixture/degraded`.
- A failed live source stays `failed` with zero records unless `--fallback-fixture` was passed; the replacement slice is then listed separately as `fixture`.
