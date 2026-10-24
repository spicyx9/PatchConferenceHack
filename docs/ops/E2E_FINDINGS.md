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
| 1 | 8a7d7d4 | 9 passed, 1 failed (step 10) | F1, F2, F3 |
| 2 | 84dbe8b | 10 passed | F2 |
| 3 | 4494e77 | 15 passed (journey + shared agent state) | F2 |
| 4 | a5e6479 | 16 passed (after the (a) fix below) | F4 |
| 5 | ff8f06a | 16 passed | none (F4 resolved by decision) |

## Open

_No open finding after the F4 decision._

## Resolved

### F4 (c, graph/core vs shared agent state): `/reset` deletes the plan history

- **Resolved by decision (user, 2026-10-24)**: `POST /reset` is a hard demo reset and does delete the
  demo user's `PLANS`, `SKIPS` and `Change`. The "invalidated, never deleted" rule applies only to
  replanning in normal use (`agent_state.write_plan` / `write_skips` / `write_change`). No code change.
- **Found in**: run 4, reading #26 (a5e6479) against the shared agent state contract (#25).
- **Symptom**: `POST /reset` now calls `GraphStore.delete_user_state`, which runs
  `MATCH (c:Change {user_id: $user_id}) DETACH DELETE c` and
  `MATCH (:User {id: $user_id})-[r:PLANS|SKIPS]->() DELETE r`. The shared agent state contract
  (`conferge/graph/agent_state.py`, from the shared-agent-state brief) says an old plan becomes
  `state: invalidated` with its previous `plan_version` and is never deleted; Change nodes are the audit
  trail of replanning. After a reset the history and the agents' write counts are gone.
- **Where**: `conferge/core/store.py:92-94` (`delete_user_state`), called from `conferge/api/app.py:710`.
- **Proposed fix**: keep deleting `Meeting` nodes (that was the F1 follow-up), but for `PLANS`/`SKIPS`
  set `state = 'invalidated'`, `invalidated_by = 'reset'`, `invalidated_at_ms` through
  `GraphStore.merge_edge` (or `agent_state.write_plan(store, user, [], written_by="reset")` and
  `write_skips(..., [])`, which already do exactly this), and keep `Change` nodes. If a hard wipe is
  wanted for the demo, make it a separate explicit endpoint and say so in the contract.

### F2 (c): goal edges without `observed_at`

- **Resolved on main by a5e6479 (#26)**: `Goal.stated_at`, set by `POST /goal` and written as `observed_at`.
  Configured demo goals keep `observed_at = null` (never the ingest time), which the test still accepts
  for `source == "user"` only.


### F1 (b, graph): ranking is lost when the API process restarts

- **Resolved on main by aa488c3 (#19, rankings computed from FalkorDB)**: `/goal` ranks from the graph
  (`computed_by: falkordb`), which reads the `Meeting` nodes, so the met person stays down after a restart.
  Run 2 passes step 10. The `/reset` question below was answered by #26 (a5e6479), see F4.

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

### F3 (c, graph): `POST /goal` does not write the new goals to FalkorDB

- **Resolved on main by aa488c3 (#19)**: `conferge/api/app.py:104` now calls `GraphIngestor(...).ingest_goals`.

- **Step**: not failing today; found while reading `/graph/path`.
- **Symptom**: the "why this person" path is queried from the `Goal` nodes ingested at start-up
  (`run_demo.py`, from `demo_goal_text`). A goal text that parses to a goal id absent at start-up
  (for example only "engineers") has no FalkorDB path and silently falls back to the API sample graph.
  It works in the demo because goal ids are deterministic slugs that the demo text already covers.
- **Where**: `conferge/api/app.py:212-240` (`/goal` updates `state.goals` only).
- **Proposed fix**: `/goal` calls `GraphIngestor(store).ingest_goals("demo-user", goals)` through the existing
  ingest path (MERGE only), and `/graph/path` reports `backend` so the fallback stays visible.

## Fixed in the e2e branch (a)

- Run 4: `PLANS`, `SKIPS` and `AFFECTS` edges written by `conferge/graph/agent_state.py` lacked the
  `confidence`, `observed_at` and `verification` fields every edge carries per `conferge/graph/schema.py:34`.
  They now carry `confidence 1.0`, `verification agent_decision` and `observed_at` = the decision time;
  covered by `test_agent_edges_carry_the_graph_provenance_contract`.

- `scripts/run_demo.py --keep-graph`: serve on the existing graph without the reset/reload, so an API
  restart can be tested at all (before, every start deleted the graph).
- The test first required `observed_at` on every edge, stricter than the graph contract; it now
  follows the contract (see F2).
