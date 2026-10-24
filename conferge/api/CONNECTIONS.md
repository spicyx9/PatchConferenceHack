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
