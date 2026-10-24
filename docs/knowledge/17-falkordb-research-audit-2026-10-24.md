# Conferge — FalkorDB research synthesis and code audit (2026-10-24)

**Scope:** seven supplied deep-research artifacts: three technical FalkorDB reports, one GraphRAG SDK report and three Opportunity Graph reports, including a duplicate; **no standalone planning/Anti-FOMO optimization research supplied**.

**Audited GitHub main:** `db0c4b9d99c4458bb0577bc4658f4550201f28a8` (2026-10-24 17:00:59 UTC). This is a documentation and implementation plan, **not a code change**. Compare with `main` before implementing. All 14 feature PRs (#1–#14) were merged and the latest GitHub CI was green when examined; README reports 926 local tests and a working 697-node graph, not independently reproduced in this audit.

## Non-negotiable architecture

1. Keep `conferge/core/store.py::GraphStore` as the sole **write** gateway. Keep explicit parameterized, read-only Cypher for graph traversal.
2. The graph must **affect the recommendation and memory-driven reranking**; a Cytoscape graph drawn from `DemoData` does not establish a graph-native recommendation.
3. `source_mode` (live / cached / fixture / mixed), source URL, observed timestamp, identity confidence, presence confidence and evidence quality must not be conflated.
4. No speaker, sponsor employee or LinkedIn person is a confirmed participant unless there is an independent attendance record. Never invent real prices or booking availability.
5. No GraphRAG SDK integration in the hackathon critical path. Structured sources + deterministic taxonomy + traceable Cypher suffice; LLM only optionally rephrases claims already backed by source IDs.

## P0 — fix and prove before the stage demo

### P0.1 Graph actually drives the top recommendations and meeting memory

**Code observed:**
- `conferge/agents/planner/agent.py` has module-level `_DEFAULT = PlannerAgent()`; `PlannerAgent(graph=None)` does rankings from `AgentContext` rather than graph hints.
- `conferge/api/app.py::DemoState.opportunities` uses `agent_opportunities` or `logic.rank_people`. `/met` updates `state.met` in Python and separately attempts a `Meeting` MERGE. A ranking change alone is not evidence that FalkorDB caused it.
- `scripts/run_demo.py` ingests a graph **after** initial planning and deletes the demo graph at startup. Do not claim cross-restart memory persistence in this mode.

**Acceptance:** On the actual demo data, one named FalkorDB read query returns the candidate person/event path and contributes a verifiable score or exclusion to `/people` / `/plan`. Record MET through `GraphStore`, requery FalkorDB, and show the changed recommendation. A deliberately unavailable graph must produce an explicitly labelled degraded/fallback mode, not the same result advertised as graph-native. A test demonstrates a graph-derived change, not simply a Python-set resort.

### P0.2 Evidence aggregation and unknown confidence

**Code observed:** `conferge/graph/queries.py::_path_confidence` returns `1.0` when no confidence is present; `people_for_goal` adds `PATH_WEIGHTS[kind] * _path_confidence(path)` per distinct graph path.

**Acceptance:** An absent edge confidence remains unknown, never 1.0. Evidence sharing a **canonical original source** contributes at most once per person/claim family. Multiple truly independent sources can raise confidence with bounded diminishing returns; repeated edges from the same page do not. `source_url` should be canonicalized or tied to a stable source ID before grouping. Tests: 1 path vs 10 duplicate paths -> same evidence score; second independent source -> bounded increase; missing confidence -> not certain.

### P0.3 Reliable explanations and safe provenance

**Code observed:** `Q_PATH_USER_TO_PERSON` uses generic undirected `shortestPath((g)-[*..5]-(person))`. The shortest topological path may have the wrong business meaning.

**Acceptance:** The primary displayed `Why?` explanation is constructed from an **approved meta-path** (goal/topic/session/speaker; goal/topic/event/host; explicitly confirmed attendee), plus actual edge IDs, source IDs and `source_mode`. A public speaker is `announced_speaker`, not `physically_present`. For UI, show only the subgraph that supports this exact decision. Keep generic shortestPath only for technical graph exploration, not factual justification.

### P0.4 Preserve what already works

Run `make check` and the live Docker FalkorDB tests before and after each small PR. Verify the current UI, screenshot and live-data capture still work. Do **not** make a large schema migration or introduce GraphRAG dependencies before the demo. Keep the labelled fixture-only fallback and public-source live result separate. For FalkorDB track, a true DB-backed path and real memory requery is more important than additional data volume.

### P0.5 Freeze a proven Docker/SDK combination

**Current code:** `docker-compose.yml` uses mutable `falkordb/falkordb:latest`; `pyproject.toml` allows `falkordb>=1.0,<3`; `conferge/graph/schema.py::INDEX_STATEMENTS` still declares legacy `CALL db.idx.fulltext.createNodeIndex(...)` DDL-like calls as data.

**Research conflict:** One report recommends 6.0.2, others 6.0.3, another 4.20.7. Official GitHub release **6.0.3 was published 2026-10-22**, and 6.x is the Rust engine. The official release 4.20.7 remains the C branch. The correct operational choice is to **inspect the running image and test the actual workload**, then pin the known-good image tag/digest (ideally 6.0.3 if the tested image is 6.0.3). Never blindly switch a successful demo to the 4.x engine, especially with a persistent 6.x volume. Use modern `CREATE FULLTEXT INDEX FOR ...` DDL instead of the old full-text creation procedure if index setup is executed; test the DDL against the chosen image. Pin the tested `falkordb` Python client (official 1.8.0 is available), using a reproducible lock.

Official: https://github.com/FalkorDB/FalkorDB/releases/tag/v6.0.3 and https://docs.falkordb.com/cypher/indexing/fulltext-index

## P1 — only if P0 and stage replay are solid

- Distinguish `Goal-[:TARGETS]->Topic` from generic `ABOUT`, `Event-[:AROUND]->Conference` from an official `PART_OF`, and `User` from `Person`. The current GraphStore allowlist lacks User/TARGETS/AROUND; migrate all ingesters, queries, agents and UI together on an integrator-owned branch rather than editing one piece opportunistically.
- Make meeting/interaction identity occurrence-aware. `conferge/graph/schema.py::memory_id(user, kind, target)` collapses repeats; preserve interaction history with unique event IDs and a separate view of current memory state. `conferge/api/app.py::met` has a similar fixed-per-person meeting ID.
- Anti-FOMO value must compare the **marginal coverage of unique people and goals**, alternate touchpoints and travel feasibility—not just event score vs event score. Existing w10 dynamic programming and minimal-change replan are a solid base; keep them.
- Vector search is optional. Index vectors with `vecf32`, wait until the index is OPERATIONAL, and validate the interpretation/order of `score` on identical vs orthogonal vectors in the running version. Official docs currently show cosine `ORDER BY score DESC`, while some reports infer distance `ASC`; **do not copy an ordering assumption blindly**.
- `algo.SPpaths` is a candidate for weighted intros; don't depend on it unless tested against the pinned server and valid edge weights. It does not replace business meta-path validation.

Official: https://docs.falkordb.com/cypher/indexing/vector-index and https://docs.falkordb.com/algorithms/sppath

## P2 — after the hackathon

- GraphRAG SDK `v1.5.0` was released on **GitHub 2026-10-22**; the PyPI page viewed in this audit still serves `1.4.0`. SDK's default ingest writes with its own GraphStore and graph vocabulary. It is not compatible with our mandatory single write gateway without an adapter. Use at most `GraphExtraction.extract` as a separate, tested optional extractor.
- Rich `Source/Assertion` or `ExternalIdentity/Appearance` nodes with temporal validity and reversible identity merges.
- Entity resolution evaluation, semantic-index recall, cross-session ROI, PageRank and betweenness only when they improve actual goal-based results.

Sources: https://github.com/FalkorDB/GraphRAG-SDK/releases/tag/v1.5.0 ; https://pypi.org/project/graphrag-sdk/

## Important conflicts between supplied reports

| Topic | Conflicting findings | What to do |
| --- | --- | --- |
| FalkorDB version | 6.0.2 vs 6.0.3 vs 4.20.7 | Inspect live Docker image; pin the version passing this repo's actual tests; do not migrate formats blindly |
| GraphRAG SDK release | 1.4.0 PyPI vs 1.5.0 GitHub | Confirm target source/package; keep entirely optional |
| Vector cosine score | Some studies: higher is better; others: lower is better | Test synthetic identical/opposite vectors before ranking |
| Graph schema | Original allowlist only permits ABOUT, PART_OF etc.; reports propose User/TARGETS/AROUND | P1 synchronized schema migration, not unilateral changes |
| Planning research | Opportunity Graph reports cover planning concepts but **no standalone optimization/OR-Tools audit supplied** | Working w09/w10 modules are already merged. Do not block demo; research further only if planner tests reveal a specific deficiency |

## Acceptance scenario for P0

1. On the real running graph, create/identify a Goal and its topics.
2. Query people via FalkorDB named read-only Cypher; return exact allowed paths.
3. Show at least one recommendation where both the **ranking signal and explanation** come from actual FalkorDB result/evidence.
4. Show two colliding events, including travel-buffer constraints.
5. Anti-FOMO chooses on unique-person/goal value and identifies what is lost and alternative touchpoints.
6. Simulate cancellation, return minimal before/after plan diff.
7. Record MET through GraphStore and rerun a graph query so the candidate's priority changes; prove state is not only `state.met`.
8. At every step, propagate `live`, `fixture` or `mixed`, provenance and unavailable-field uncertainty accurately. If no Bright Data key is configured, say so; never claim Bright Data live.

**Operator priority:** The prototype already exists. Fix the weakest epistemic and graph-native claims with small tests, then rehearse the three-minute stage demo. Do not add a large new framework or switch to a different database.
