# Verify the results

All offline checks read committed evidence and require no API key or network access. Access metrics are recalculated from all 21 site-level attempt records—the union of two direct user-agent attempts, Web Unlocker, and Dataset outcomes—and then cross-checked against the stored summary.

```bash
uv run python scripts/verify_judge_evidence.py --check
uv run python scripts/verify_judge_evidence.py --json
```

| Claim | Repository source | Verification |
|---|---|---|
| 34 Google Flights observations via Web Unlocker | [`data/cache/flights.json`](../../data/cache/flights.json) | `uv run python scripts/verify_judge_evidence.py --check` |
| 21 lodging records: 15 Booking, 6 Airbnb | [`data/cache/stays.json`](../../data/cache/stays.json) | same command |
| 17 LinkedIn public profiles | [`data/cache/linkedin_public.json`](../../data/cache/linkedin_public.json) | same command |
| 2 Crunchbase company records | [`data/cache/crunchbase_public.json`](../../data/cache/crunchbase_public.json) | same command |
| Access matrix: 21 sites; 10 direct, 14 Bright Data, 12 Unlocker, 16 any path | [`data/block_matrix.json`](../../data/block_matrix.json) | same command |
| Historical graph: 690 nodes / 2,184 relationships loaded | [`STATUS.md`](../../STATUS.md) | Start the demo, then run the read-only commands below before plan mutation |
| Ryan Hecht ranking and meeting-memory change | [`STATUS.md`](../../STATUS.md), [`tests/api/test_graph_ranking.py`](../../tests/api/test_graph_ranking.py) | `uv run pytest -q tests/api/test_graph_ranking.py` |
| Sold-out event is removed and replaced with an explained alternative | [`tests/api/test_replan.py`](../../tests/api/test_replan.py) | `uv run pytest -q tests/api/test_replan.py` |
| Evidence path comes from FalkorDB | [`tests/api/test_live_graph.py`](../../tests/api/test_live_graph.py) | `uv run pytest -q tests/api/test_live_graph.py` |
| Full repository health | [`Makefile`](../../Makefile) | `make check` |

## Live graph verification

After `make up` and `uv run python scripts/run_demo.py --travel fixture`, use read-only FalkorDB queries:

```bash
redis-cli -p 6379 GRAPH.RO_QUERY conferge_demo "MATCH (n) RETURN count(n)"
redis-cli -p 6379 GRAPH.RO_QUERY conferge_demo "MATCH ()-[r]->() RETURN count(r)"
```

The exact count depends on whether plan, skip, change, and meeting state has already been written. Reset before comparing with a captured baseline. Do not treat the historical figure as a live value without running these queries.

## Claim boundaries

- Flight records are outbound observations with page-quoted totals, not verified round trips or bookings.
- Lodging records are captured quotes, not verified availability or reservations.
- LinkedIn enrichment corroborates a public profile; it does not prove conference attendance or a ranking improvement.
- The sold-out condition is a labelled simulation.
- The undefined “16-endpoint subset” is omitted; only the complete 21-site access matrix is reported.
