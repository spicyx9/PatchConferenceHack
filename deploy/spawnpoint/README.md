# Spawnpoint deployment

The public app is `conferge` at https://conferge-fx6pnv.spwt.app.
Use the Docker runtime. The root Dockerfile matches the working deployment in
`integrations/trueforge/Dockerfile`: FalkorDB, FastAPI, private TrueForge hosted
mode, and a private MCP adapter. Only FastAPI listens publicly on port 8080.
See `integrations/trueforge/README.md` for the tool flow and runtime details.

## Build and upload

After committing the release, export dependencies if uv.lock changed:

```sh
uv export --no-dev --no-emit-project --no-hashes --output-file requirements.txt
python3 deploy/spawnpoint/bundle.py
```

The command prints a staging folder containing tracked application files and
`raw/connection-photos`. It excludes .env, .git, temporary artifacts and unrelated
scraped data. The cache is deliberately not committed; restore its manifest and
images locally before packaging. Official roster headshots are also populated at
startup. The finished branded brief is `docs/demo/Conferge_Brief.pdf`.

Use Spawnpoint create_upload, execute its upload command from the staging folder,
and call deploy_project with name `conferge`, runtime `docker`, and upload_id.
On redeploy, omit env to preserve the configured secrets and database connection.
Wait for running status, then verify the directory, photos and a real call to
`POST /api/v1/connections/agent-search`. Expect `agent_runtime: trueforge` and
successful search and graph-evidence tool calls. Verify deployed static files
against the staged files to confirm the intended release is serving.

## Environment and persistence

Required secrets: OPENAI_API_KEY, DATABASE_URL, TRUEFORGE_API_KEY. Keep them in
Spawnpoint's environment, never in the bundle. CONNECTIONS_OPENAI_MODEL selects
the existing OpenAI model. Do not enable a different inference provider implicitly.

FalkorDB persists under `${SPAWNPOINT_DATA_DIR:-/data}/conferge-graph`.
TrueForge uses Postgres for sessions and Redis on loopback port 6381 for runtime
coordination. Its admin API (8790) and MCP adapter (8792) are not public.
The shared hackathon demo uses the dated event snapshot and cached travel prices;
it does not book travel or send messages.
