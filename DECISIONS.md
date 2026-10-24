# Architectural decisions — 2026-10-23

| ID | Decision | Reason |
|---|---|---|
| D001 | One Python 3.11+ package, installed with uv | Shared stable contracts and independent providers |
| D002 | Each workstream owns its directory, tests and probe | Prevent concurrent edit conflicts |
| D003 | Bright Data client in `conferge.core.brightdata` | Consistent auth, async/sync scraping, retries and safe logging |
| D004 | FalkorDB graph writes only through `GraphStore` | Typed MERGE with parameterized values |
| D005 | All source results must include provenance, timestamps and termination | Visible coverage and data correctness |
| D006 | Fixtures explicit opt-in and labeled | Never misrepresent demonstration data as live |
| D007 | USD prices must preserve source currency and total; flight amounts strings | No accidental assumptions or float drift |
| D008 | Repository: `PatchConferenceHack`; product: `Conferge` | Project naming |
| D009 | FastAPI route implementation owned by window 12 | Window 0 builds contracts only; no shared route edits |
| D010 | Core contract version 0.1 | All parallel windows branch only once these contracts are on main |
| D011 | `GraphStore.merge_edge` attaches a rule-based `rationale` and `evidence_ids` (source URL, snapshot id; app-owned records cite `record:<Kind>:<id>`) to every edge and refuses an edge without evidence; ids accumulate across MERGEs | Every graph claim cites existing evidence, without an LLM |

Changes require a small, dedicated window-0 PR. Append decisions; do not rewrite history.
