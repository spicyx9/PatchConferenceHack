# Probe: api (window 12)

- collected_at: 2026-10-24T06:33:58.638290+00:00
- routes source: `fixtures/api.json` (**fixture**, fictional records, labelled `[FIXTURE]` / `(fictional)`)
- routes checked: 18, non-200: 0, responses claiming live: 0
- POST /goal with demo text: 10 people, plan days ['2026-10-27', '2026-10-28', '2026-10-29'], conflicts 1, computed_by `api-fallback`
- status: ok (API layer works; data is fixture so every envelope reports status `degraded`)

## Integrations

- FalkorDB (127.0.0.1:6380): reachable, FalkorDB reachable but graph empty or unreadable
- Bright Data: not called by the API layer (source windows own collection); no key tonight

| agent module | available | detail |
|---|---|---|
| planner | False | not merged yet |
| networking | False | not merged yet |
| antifomo | False | not merged yet |
| replanner | False | not merged yet |

## Routes

| route | http | data_source | status |
|---|---|---|---|
| POST /api/v1/goal | 200 | fixture | degraded |
| GET /health | 200 | n/a | ok |
| GET /api/v1/conference | 200 | fixture | degraded |
| GET /api/v1/plan | 200 | fixture | degraded |
| GET /api/v1/people | 200 | fixture | degraded |
| GET /api/v1/events | 200 | fixture | degraded |
| GET /api/v1/sessions | 200 | fixture | degraded |
| GET /api/v1/stays | 200 | fixture | degraded |
| GET /api/v1/flights | 200 | fixture | degraded |
| GET /api/v1/travel | 200 | fixture | degraded |
| GET /api/v1/travel/map | 200 | fixture | degraded |
| GET /api/v1/graph | 200 | fixture | degraded |
| GET /api/v1/graph/path?person=per-fx-07 | 200 | fixture | degraded |
| GET /api/v1/scenarios | 200 | fixture | degraded |
| GET /api/v1/roi | 200 | fixture | degraded |
| GET /api/v1/sources | 200 | fixture | degraded |
| POST /api/v1/simulate-change | 200 | fixture | degraded |
| POST /api/v1/met | 200 | fixture | degraded |
