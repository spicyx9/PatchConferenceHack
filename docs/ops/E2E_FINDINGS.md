# End-to-end findings

`tests/e2e/test_full_journey.py` (`make e2e`) runs the demo journey against the real API process
(`scripts/run_demo.py`, fixture sources) and the real FalkorDB at 127.0.0.1:6380, no mock.
Each failure is classified:

- (a) bug in files owned by the e2e session (tests/, planner, antifomo, front, run_demo.py): fixed in place;
- (b) bug in files owned by another session: written here, code untouched;
- (c) contract inconsistent between modules: written here, priority over (b).

Owners: **graph** = FalkorDB session (`conferge/graph`, ranking in `conferge/api`);
**travel** = travel session (`conferge/integration/assemble.py`, `stays_flights.py`, `pyproject.toml`).

## Run log

| Run | main at | Result | Open findings |
|---|---|---|---|
| 1 | 73a1f24 | 9 passed, 1 failed (step 10) | F1, F2, F3 |

## Open

### F1 (b, graph): ranking is lost when the API process restarts

- **Step**: `test_10_restart_keeps_ranking`.
- **Symptom**: after `POST /met` the met person drops from rank 0 to rank 9; after restarting the API on the
  same graph (`run_demo.py --keep-graph`) they are back at rank 0. The meeting is in FalkorDB
  (`MATCH (m:Meeting)-[:MET]->(p) RETURN m.user_id, p.id` returns `demo-user`, the person) but the API never reads it.
- **Where**: `conferge/api/app.py:68-72` (`DemoState.reset` sets `self.met = {}`) and `conferge/api/app.py:149`
  (`create_app` builds the state without reading graph memory). `/met` writes at `conferge/api/app.py:476-479`.
- **Proposed fix**: after `DemoState.reset()` in `__init__`, when `graph_probe` and a store is reachable, seed
  `self.met` from `conferge.graph.people_met_before(store, "demo-user")` rows with `kind == "MET"` (the networking
  reader already does this: `conferge/agents/networking/graph_reader.py:29`). Decide what `/reset` means for the
  graph: today it clears memory in the process but leaves `Meeting` nodes, so with the fix above a reset followed
  by a restart would bring the meetings back. Either `/reset` stays process-only (document it) or it invalidates
  the user's `Meeting` nodes through a `GraphStore` method.

### F2 (c, graph/core): user goals have no timestamp, so goal edges cannot carry `observed_at`

- **Step**: `test_05_top5_paths_in_falkordb_with_provenance` (passes after aligning the test with the contract).
- **Symptom**: the 5 `(Goal)-[:ABOUT]->(Topic)` edges have `source=user`, `verification=user_goal` but
  `observed_at=null`; every other edge on the top-5 paths has a timestamp.
- **Where**: `conferge/graph/ingest.py:307-316` (`ingest_goals` passes `evidence=[]`), contract in
  `conferge/graph/schema.py:34` ("observed_at None when the source has no timestamp; never the ingest time"),
  `conferge/core/schemas.py:333` (`Goal` has no `created_at`).
- **Proposed fix**: window 0 adds an optional `stated_at: AwareDatetime | None` to `Goal`, `POST /goal` sets it,
  `ingest_goals` writes it as `observed_at`. Until then the e2e test accepts `observed_at=null` only when
  `evidence_source == "user"`.

### F3 (c, graph): `POST /goal` does not write the new goals to FalkorDB

- **Step**: not failing today; found while reading `/graph/path`.
- **Symptom**: the "why this person" path is queried from the `Goal` nodes ingested at start-up
  (`run_demo.py`, from `demo_goal_text`). A goal text that parses to a goal id absent at start-up
  (for example only "engineers") has no FalkorDB path and silently falls back to the API sample graph.
  It works in the demo because goal ids are deterministic slugs that the demo text already covers.
- **Where**: `conferge/api/app.py:212-240` (`/goal` updates `state.goals` only).
- **Proposed fix**: `/goal` calls `GraphIngestor(store).ingest_goals("demo-user", goals)` through the existing
  ingest path (MERGE only), and `/graph/path` reports `backend` so the fallback stays visible.

## Fixed in the e2e branch (a)

- `scripts/run_demo.py --keep-graph`: serve on the existing graph without the reset/reload, so an API
  restart can be tested at all (before, every start deleted the graph).
- The test first required `observed_at` on every edge, stricter than the graph contract; it now
  follows the contract (see F2).
