# Connections search

Open `http://127.0.0.1:8000/#graph` with the local demo API and FalkorDB running.
Set `OPENAI_API_KEY` in the local `.env` and restart the API to enable semantic search.
Do not commit the key. `CONNECTIONS_OPENAI_MODEL` optionally overrides the explanation model
(default `gpt-5.6-terra`). Embeddings use `text-embedding-3-small` at 512 dimensions.

The first search embeds public profile and session fields. FalkorDB stores the vectors,
model and content hash on Person nodes through the GraphStore write boundary. Later
searches reuse unchanged embeddings. The query is embedded, FalkorDB retrieves candidates,
and OpenAI returns evidence-based reasons. Unknown result IDs are rejected. Private meeting
notes are excluded from model input. Empty saved lists stay empty. Without a key, the UI
explicitly uses keyword matching; it does not simulate AI answers.

`Conference people` is the loaded directory; `People I've met` is scoped to recorded
meetings for the existing demo user. This does not import an address book or provide
multi-user isolation. Profile evidence retains fixture/live labels and source links.
The light 3D galaxy supports drag/keyboard rotation, zoom, depth-scaled nodes and a
pausable orbit (off by default with reduced-motion preferences). Positions are visual
layout coordinates, not relationship strengths. The galaxy overview includes every person in the selected list, with their graph
neighbourhoods and five featured goal paths. Selecting a person shows their neighbourhood
and goal path; All connections clears the search or focus and restores the full list. Vector relevance is not represented as factual confidence.

Validation: unit tests cover scope, malformed embeddings and rejecting unknown model IDs.
The vector adapter, index creation, cache and scoped nearest-neighbour query were also
checked against local FalkorDB 6.0.3 using a separate disposable test graph. Live OpenAI search was verified locally with a configured key: 183 profile embeddings
were cached in FalkorDB, and the Responses API returned six scoped matches with
profile-based reasons. The browser search flow also passed. This is a functional
smoke test, not a retrieval-quality evaluation; the account balance remains unverified.

Company, role and profile/session-topic filters combine with AND semantics. Options
come from the current scope, and filtering happens before keyword or vector retrieval.
All connections / Reset filters clear the query and all filters within the current scope.
Changing a filter returns to the filtered overview without making a paid AI call.

## Profile photos

Run `FALKORDB_PORT=6380 FALKORDB_GRAPH=conferge_demo uv run python -m conferge.api.photos`
against the local server to enrich the current directory through Bright Data Web Unlocker.
Only existing LinkedIn profile links on those Person nodes are used; no name-only searches.
The collector accepts LinkedIn profile-photo CDN URLs, downloads images immediately with
a 5 MB cap, and caches files and source metadata under Git-ignored `raw/connection-photos/`.
FalkorDB receives photo location/provenance through GraphStore. Existing cached people are
skipped on reruns. Missing or inaccessible photos retain initials. Images are displayed in
the sidebar and focused 3D views, with separate live photo provenance from fixture profiles.
The photo cache is local data and is not included in a Git-based deployment.

Local enrichment on 2026-10-24 processed 165 linked directory profiles and retried three
provider errors once. Final result: 77 photos cached, 88 linked profiles without a usable
photo, and 18 directory members without a linked profile. Use repeated `--name` arguments
for targeted retries. The complete offline suite passed with credentials excluded from
settings (1,114 passed, 22 skipped); the real image endpoint and browser were also checked.

### Public founder and investor roster (2026-10-24)

`network_roster.json` contains ten sourced public profiles from the official
[Heavybit](https://heavybit.capital/team) and
[Work-Bench](https://www.work-bench.com/team) team pages. Five also have verified
co-founder backgrounds. All are `relevant_candidate` with no event IDs or
attendance claims. Each has dated source evidence and an official headshot URL.

Enable with `CONFERGE_NETWORK_ROSTER=1` when starting the demo API. Import the
company/person/topic graph and cache the official headshots with:

```sh
FALKORDB_PORT=6380 FALKORDB_GRAPH=conferge_demo uv run python -m conferge.api.network_roster
CONFERGE_NETWORK_ROSTER=1 FALKORDB_PORT=6380 uv run python scripts/run_demo.py --keep-graph --mode fixture --travel fixture
```

The importer uses GraphIngestor/GraphStore and creates no attendance edges.
Repeated runs skip cached photos. All ten photos downloaded successfully:
local directory 193 people, 87 total cached portraits. Official portraits are
attributed separately from LinkedIn/Bright Data photos. Caches under `raw/`
remain local and must be provisioned separately on a deployment. AI search
indexes the new candidates on demand; a live investor/devtools/AI query returned
Jonathan Lehr, Daniel Chesley, Proby Shandilya and Amir Zohrenejad.

Validation: Ruff, JavaScript syntax, 1,116 tests passed (22 skipped; provider
credentials isolated), live semantic search, investor filter and portrait preview.
