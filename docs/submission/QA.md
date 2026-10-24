# Judge Q&A

Fifteen questions a judge may ask, each answered in at most two sentences. Every answer points
to code (`file:line`, on `main`) or to an endpoint you can open during the demo. Figures were measured on dfca2bf at 15:33 PDT (`STATUS.md`); the table at the end says
where each one is read. Never say
a number the screen does not show.

### 1. Is this live or cached?
Stays and flights are records from earlier Bright Data collections. They are served as
`cached` with their own `collected_at`, and never relabelled `live`
(`conferge/integration/travel_cache.py:62`); open `/api/v1/stays` or `/api/v1/flights` to see
`source_mode` and `collected_at` on every item. Only the "Refresh via Bright Data" button calls
Bright Data live, and `/api/v1/pipeline` then says `cached`, `live` or `mixed` from its rows
(`conferge/api/app.py:202`).

### 2. What did Bright Data cost?
We cannot tell you the bill: no Bright Data response we captured carried a cost
(`conferge/core/cost.py:17`). `/api/v1/brightdata` shows the 39 requests and 81 records behind our cache;
we do not quote a dollar figure.

### 3. Why a graph and not Postgres?
The ranking is a traversal (user → goal → person → event) where every edge carries its
evidence, read with Cypher (`people_for_goal`, `conferge/graph/queries.py:286`), and the "why"
of each answer is built from those same paths (`/api/v1/graph/why/<person_id>`). Postgres
could store the rows, but we would have to rebuild path queries and per-edge provenance by
hand; in FalkorDB they are the data model.

### 4. What happens if Bright Data is down?
Each call is bounded (`MAX_RETRIES`, and `COOLDOWN_DELAYS` for `no_peers` or cooldown,
`conferge/core/brightdata.py:32-35`), and a failed source becomes a `degraded` or `failed` row
with its reason in `/api/v1/pipeline` while the demo keeps serving the cache. Without a cache,
stays fall back to pyairbnb, labelled as a fallback, only when every Bright Data source
returned nothing (`conferge/lodging/service.py:78`).

### 5. Is the return flight included?
No. The Google Flights page lists outbound legs with the round-trip total, so we show that
total unchanged with `return_slice_collected: false`
(`conferge/flights/round_trip_total.py:41`). The return leg's times and flight numbers are not
collected, and every item in `/api/v1/flights` says so.

### 6. Why 2 adults?
The stay search uses the trip brief's `ADULTS` (`conferge/integration/stays_flights.py:41`).
Flights are searched for one adult in economy (`conferge/flights/unlocker_provider.py:206`), and
the screen says so beside every trip total ("Stay quoted for 2 adults · flight for 1 adult",
`occupancy_note` in `/api/v1/travel` and `/api/v1/roi`).

### 7. Why did Nick Liffen disappear after "I met"?
`people_for_goal` excludes people the user has already MET or CONTACTED, read from Meeting
nodes in FalkorDB (`conferge/graph/queries.py:281-283`, applied at `:293`), so the ranking
moves on to people you have not met. The MET lives in the graph, so the exclusion survives a
restart (`tests/api/test_graph_ranking_live.py:60`); `/api/v1/people` then omits him instead of
listing him as met.

### 8. Which sites did Bright Data fail on, and why?
The Web Unlocker refuses Kayak, Hotels.com, Expedia and Marriott until the account is KYC
approved, and the client raises that refusal (`conferge/core/brightdata.py:404-406`); the
Google Hotels dataset answered `no_peers`, and the Google Flights dataset ran past our time
budget. `/api/v1/pipeline` → `reachability` lists all 21 sites:
10 reachable without Bright Data,
14 with it.

### 9. How is the score computed?
For each goal, a person's path contributions are combined per source (the best per source,
then a noisy-OR across independent sources, `conferge/graph/queries.py:238`) and weighted by
the goal's priority (`:333`); the goal scores are then summed and capped
(`conferge/graph/ranking.py:60`). Each card in `/api/v1/people` returns its `score_breakdown`.

### 10. Is the sold-out real?
No. It is a labelled simulation, "SIMULATION (not observed)"
(`conferge/integration/assemble.py:106`), applied to the top event of the current plan by
`/api/v1/simulate-change` to show the replan diff. Nothing in the demo reports a real sold-out.

### 11. Can I run it on my laptop?
Yes: `make up`, `make install`, `make demo` (`Makefile:25`, `:9`, `:39`), first screen in
3 without any key. A busy port fails fast with the command to run
instead (`Makefile:25`), and without FalkorDB the demo still serves, degraded, with "FalkorDB
unreachable on host:port" in the Data pipeline panel (`scripts/run_demo.py:194`).

### 12. How do you avoid inventing values?
A missing price stays null: never 0, never estimated (`conferge/lodging/normalize.py:49`). A
round-trip total is never split into legs (`conferge/flights/round_trip_total.py:41`), a
Crunchbase total is a sum only when every round lists its amount
(`conferge/people/crunchbase.py:438`), and a LinkedIn profile attaches only on the same URL with
the same first and last name (`conferge/integration/people_linkedin.py:456`).

### 13. What does FalkorDB do that Python could not?
With FalkorDB down, the API answers in an explicit `degraded_no_graph` mode and the ranking
changes (`tests/api/test_graph_ranking.py:86`): the graph is the ranking, not decoration. The
graph also holds what a Python list in one process does not: memory across restarts (MET,
`tests/api/test_graph_ranking_live.py:60`) and the explainable path behind each answer
(`/api/v1/graph/why/<person_id>`).

### 14. What is simulated in the demo?
The sold-out change (`conferge/integration/assemble.py:106`) and the fictional placeholder rows
of `fixtures/api.json`, all labelled. Events and people with `data_source: fixture` are a
labelled snapshot of the public collection, not a live read; check `/api/v1/sources`.

### 15. What is next?
Three gaps the code already reports:
- the Unlocker sites waiting for KYC (`/api/v1/pipeline` → `reachability`,
  18 sites if approved);
- a Google Flights dataset snapshot with prices, which takes over from the Unlocker totals once
  one arrives (`conferge/flights/snapshot_provider.py:35`);
- Google Hotels direct, whose page renders Google's default dates, so its prices are discarded
  (`conferge/lodging/google_hotels_direct.py:191`).

## Where each figure is read

| Value | Endpoint and field |
|---|---|
| 39 | `/api/v1/brightdata` → `cache_summary.requests_at_collection_time` |
| 81 | `/api/v1/brightdata` → `cache_summary.records` |
| 21 | `/api/v1/pipeline` → `reachability.counts.n` |
| 10 | `/api/v1/pipeline` → `reachability.counts.reachable_without_brightdata` |
| 14 | `/api/v1/pipeline` → `reachability.counts.reachable_with_brightdata` |
| 18 | `/api/v1/pipeline` → `reachability.counts.reachable_with_brightdata_if_kyc_approved` |
| 3 | `make predemo` → "up in N s" |
