# FalkorDB: the opportunity graph

FalkorDB is Conferge's relationship and memory layer. It connects goals, topics, events, people, companies, venues, opportunities, and meetings so every recommendation can expose the path that produced it.

## What the graph makes possible

- **Multi-hop recommendations.** Bounded Cypher signatures traverse `Goal → Topic ← Event ← Person`, confirmed attendance, host-company, company-topic, direct-topic, and opportunity paths.
- **Evidence-aware scoring.** Each path uses its weakest edge confidence; independent root sources are combined with noisy-OR so duplicated evidence does not inflate confidence.
- **Inspectable explanations.** A person card can return the actual nodes, relationships, provenance, and copyable Cypher—not a prose explanation invented after ranking.
- **Durable meeting memory.** Recording a meeting creates a `Meeting` occurrence and `MET`/`INVOLVES` relationships; a fresh application instance reads that memory back.
- **Impact-aware replanning.** Graph traversals identify affected people and alternative events when an event is marked sold out. Python applies the final minimal-change planning decision and produces the diff.

## Implementation map

| Capability | Evidence |
|---|---|
| Parameterized, allowlisted graph writes; indexes | [`conferge/core/store.py`](../../conferge/core/store.py) |
| Read-only traversals, path signatures, confidence and noisy-OR | [`conferge/graph/queries.py`](../../conferge/graph/queries.py) |
| Person and event ranking | [`conferge/graph/ranking.py`](../../conferge/graph/ranking.py) |
| Meeting occurrence persistence | [`conferge/graph/memory.py`](../../conferge/graph/memory.py) |
| API orchestration and final replan | [`conferge/api/app.py`](../../conferge/api/app.py) |
| Memory survives fresh app state | [`tests/api/test_graph_ranking.py`](../../tests/api/test_graph_ranking.py) |
| Sold-out removal, replacement, reason, and path | [`tests/api/test_replan.py`](../../tests/api/test_replan.py) |

Reads prefer the driver's `ro_query` method. Full-text indexes cover `Person(name, bio)` and `Event(title)`. Writes are confined to `GraphStore` MERGE operations and explicit memory/state operations.

## Captured demo result

On the recorded judge demo, the loaded catalogue measured **690 nodes and 2,184 relationships** before plan state, and **691 nodes and 2,213 relationships** after one user, 25 `PLANS`, and 4 `SKIPS` relationships were written. These are historical captured values in [`STATUS.md`](../../STATUS.md), not a claim about a currently running database.

The same capture ranked 50 people; 13 of those cards had Bright Data LinkedIn enrichment. Ryan Hecht ranked first at 56. After “I met Ryan Hecht,” the graph memory removed him from the next-contact ranking and the next candidates moved up. Exact recorded values and live verification queries are in [VERIFY.md](VERIFY.md).

## Division of responsibility

FalkorDB answers relationship questions: who is connected, through which evidence path, who is affected, and what alternatives share people or topics. The deterministic Python planner owns schedule feasibility and the final replacement. This separation keeps graph-derived impact explainable without pretending Cypher makes every product decision.
