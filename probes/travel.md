# Probe: travel (window 11)

- collected_at: 2026-10-24T07:30:01.220177+00:00 (started 2026-10-24T07:29:56.446433+00:00)
- probe departure input: 2026-10-27T18:00:00-07:00 (America/Los_Angeles); not a flight time
- data: live calls only; nothing in this report is fixture

## San Francisco International Airport -> Fort Mason Center

status **degraded**, source_mode `live`, options 2

- report `bart`: ok/exhausted, fetched 3, unique 3
- report `osrm`: ok/exhausted, fetched 1, unique 1, warnings: OSRM foot profile estimate
- report `osrm`: ok/exhausted, fetched 1, unique 1, warnings: OSRM free-flow driving time, no live traffic; taxi/rideshare fare unknown
- report `uber_estimator`: failed/error, fetched 0, unique 0, errors: uber estimator: BRIGHTDATA_UNLOCKER_ZONE not configured
- note: uber estimator: BRIGHTDATA_UNLOCKER_ZONE not configured
- note: Muni/Caltrain/VTA legs not computed: 511.org transit key not configured

| option | leg | mode | depart | arrive | min (status) | price (status) | provider | source_mode | source |
|---|---|---|---|---|---|---|---|---|---|
| BART to Embarcadero BART then walk | 1 airport-sfo -> station-bart-embr | bart ROUTE 2 | 2026-10-27 18:00 -0700 | 2026-10-27 18:31 -0700 | 31 (scheduled) | 11.80 USD (exact) | bart | live | https://api.bart.gov/api/sched.aspx?cmd=depart&orig=SFIA&dest=EMBR&date=10%2F27%2F2026&time=6%3A00pm&b=0&a=3&json=y |
| BART to Embarcadero BART then walk | 2 station-bart-embr -> venue-fort-mason | walk | 2026-10-27 18:31 -0700 | 2026-10-27 19:24 -0700 | 54 (estimate) | 0 USD (exact) | osrm | live | https://routing.openstreetmap.de/routed-foot/route/v1/foot/-122.3975,37.7929;-122.432,37.806?overview=false |
| **BART to Embarcadero BART then walk total** | | | | | 85 | 11.80 USD (exact) | complete=True | | |
| Taxi or rideshare (driving time) | 1 airport-sfo -> venue-fort-mason | drive | 2026-10-27 18:00 -0700 | 2026-10-27 18:28 -0700 | 29 (estimate) | null (unknown) | osrm | live | https://router.project-osrm.org/route/v1/driving/-122.379,37.6213;-122.432,37.806?overview=false |
| **Taxi or rideshare (driving time) total** | | | | | 29 | null (unknown) | complete=False | | |

## Oakland International Airport -> Fort Mason Center

status **degraded**, source_mode `live`, options 2

- report `bart`: ok/exhausted, fetched 3, unique 3
- report `osrm`: ok/exhausted, fetched 1, unique 1, warnings: OSRM foot profile estimate
- report `osrm`: ok/exhausted, fetched 1, unique 1, warnings: OSRM free-flow driving time, no live traffic; taxi/rideshare fare unknown
- report `uber_estimator`: failed/error, fetched 0, unique 0, errors: uber estimator: BRIGHTDATA_UNLOCKER_ZONE not configured
- note: uber estimator: BRIGHTDATA_UNLOCKER_ZONE not configured
- note: Muni/Caltrain/VTA legs not computed: 511.org transit key not configured

| option | leg | mode | depart | arrive | min (status) | price (status) | provider | source_mode | source |
|---|---|---|---|---|---|---|---|---|---|
| BART to Embarcadero BART then walk | 1 airport-oak -> station-bart-embr | bart ROUTE 19 + ROUTE 11 | 2026-10-27 18:00 -0700 | 2026-10-27 18:36 -0700 | 36 (scheduled) | 13.45 USD (exact) | bart | live | https://api.bart.gov/api/sched.aspx?cmd=depart&orig=OAKL&dest=EMBR&date=10%2F27%2F2026&time=6%3A00pm&b=0&a=3&json=y |
| BART to Embarcadero BART then walk | 2 station-bart-embr -> venue-fort-mason | walk | 2026-10-27 18:36 -0700 | 2026-10-27 19:29 -0700 | 54 (estimate) | 0 USD (exact) | osrm | live | https://routing.openstreetmap.de/routed-foot/route/v1/foot/-122.3975,37.7929;-122.432,37.806?overview=false |
| **BART to Embarcadero BART then walk total** | | | | | 90 | 13.45 USD (exact) | complete=True | | |
| Taxi or rideshare (driving time) | 1 airport-oak -> venue-fort-mason | drive | 2026-10-27 18:00 -0700 | 2026-10-27 18:39 -0700 | 40 (estimate) | null (unknown) | osrm | live | https://router.project-osrm.org/route/v1/driving/-122.2197,37.7126;-122.432,37.806?overview=false |
| **Taxi or rideshare (driving time) total** | | | | | 40 | null (unknown) | complete=False | | |

## San Jose Mineta International Airport -> Fort Mason Center

status **degraded**, source_mode `live`, options 1

- report `osrm`: ok/exhausted, fetched 1, unique 1, warnings: OSRM free-flow driving time, no live traffic; taxi/rideshare fare unknown
- report `uber_estimator`: failed/error, fetched 0, unique 0, errors: uber estimator: BRIGHTDATA_UNLOCKER_ZONE not configured
- note: uber estimator: BRIGHTDATA_UNLOCKER_ZONE not configured
- note: Muni/Caltrain/VTA legs not computed: 511.org transit key not configured
- note: San Jose Mineta International Airport: no BART station; rail option not computed

| option | leg | mode | depart | arrive | min (status) | price (status) | provider | source_mode | source |
|---|---|---|---|---|---|---|---|---|---|
| Taxi or rideshare (driving time) | 1 airport-sjc -> venue-fort-mason | drive | 2026-10-27 18:00 -0700 | 2026-10-27 19:08 -0700 | 69 (estimate) | null (unknown) | osrm | live | https://router.project-osrm.org/route/v1/driving/-121.9289,37.3639;-122.432,37.806?overview=false |
| **Taxi or rideshare (driving time) total** | | | | | 69 | null (unknown) | complete=False | | |

## Fort Mason Center -> Embarcadero BART

status **degraded**, source_mode `live`, options 2

- report `osrm`: ok/exhausted, fetched 1, unique 1, warnings: OSRM foot profile estimate
- report `osrm`: ok/exhausted, fetched 1, unique 1, warnings: OSRM free-flow driving time, no live traffic; taxi/rideshare fare unknown
- report `uber_estimator`: failed/error, fetched 0, unique 0, errors: uber estimator: BRIGHTDATA_UNLOCKER_ZONE not configured
- note: uber estimator: BRIGHTDATA_UNLOCKER_ZONE not configured

| option | leg | mode | depart | arrive | min (status) | price (status) | provider | source_mode | source |
|---|---|---|---|---|---|---|---|---|---|
| Walk | 1 venue-fort-mason -> station-bart-embr | walk | 2026-10-27 18:00 -0700 | 2026-10-27 18:53 -0700 | 54 (estimate) | 0 USD (exact) | osrm | live | https://routing.openstreetmap.de/routed-foot/route/v1/foot/-122.432,37.806;-122.3975,37.7929?overview=false |
| **Walk total** | | | | | 54 | 0 USD (exact) | complete=True | | |
| Taxi or rideshare (driving time) | 1 venue-fort-mason -> station-bart-embr | drive | 2026-10-27 18:00 -0700 | 2026-10-27 18:09 -0700 | 10 (estimate) | null (unknown) | osrm | live | https://router.project-osrm.org/route/v1/driving/-122.432,37.806;-122.3975,37.7929?overview=false |
| **Taxi or rideshare (driving time) total** | | | | | 10 | null (unknown) | complete=False | | |

