# Conferge + TrueForge local tooling demo

Tested with TrueForge 0.180.0 on October 24, 2026. This is a working local
integration against the public Conferge API, not the runtime behind the site's
Connections search box. The production site continues to call OpenAI directly.

## Run

Requires Node 22.14+ and uv. In separate terminals, from the repository root:

```sh
HOST=127.0.0.1 OUTBOUND_URL_ALLOWED_HOSTS='["127.0.0.1"]' npx --yes @truefoundry/trueforge@0.180.0 --port 8790
uv run integrations/trueforge/server.py
```

The specific loopback exception lets TrueForge reach the local MCP server.
Both services bind to loopback; do not expose unauthenticated local mode publicly.

Put OPENAI_API_KEY in the ignored project .env or environment, then:

```sh
uv run integrations/trueforge/configure.py
uv run integrations/trueforge/probe.py
```

Configure registers the existing OpenAI model and local connector. TrueForge
stores provider credentials in its local application data; no key is in these
files. The probe saves a reusable `conferge-networking` agent and runs a real
streamed turn. Inspect it at http://127.0.0.1:8790 under Sessions or Agents.
Raw trace: `/tmp/conferge-trueforge-trace.json` (not committed).

## Tools

- `search_connections`: OpenAI/FalkorDB semantic search, with optional filters.
  May populate embeddings; does not change meeting records or agenda.
- `connection_filters`: valid company, role and topic values.
- `explain_connection`: goal-to-person graph path and source evidence;
  missing paths are explicit, not fabricated.

Tools preserve source and fixture/cache information. Failures propagate as MCP
errors. The API base is fixed by the operator via CONFERGE_API_URL, never chosen
by the model. Photos are omitted from search context.

The agent uses read-only tools; write/destructive approval rules are configured,
but no write tool is exposed and no approval pause is claimed as tested.
Sandbox, skills, subagents and outbound messaging are not enabled.

## Observed result

Session `01m5r1ghth8cj8gnfrnmqdfx26` completed with status `done` after two
successful tool responses: `search_connections`, then `explain_connection`.
It recommended Peli de Halleux and Alexander Lichter for developer tools,
cited the official catalog and explained Peli's three-hop goal/topic/session/
speaker path. It explicitly distinguished fixture/catalog evidence from live
attendance and personal relationships. This is a functional smoke test, not
a retrieval-quality benchmark.
