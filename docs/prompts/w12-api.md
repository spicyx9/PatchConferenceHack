# Conferge — Window 12 / FastAPI demo UI

**Repo:** spicyx9/HTest. **Branch:** `w12-api`. **Owner:** `conferge/api/ and static/` plus matching `tests/api/`, `scripts/probes/api.py`, `fixtures/api.json` and `probes/api.md` only.

Read `CLAUDE.md`, `docs/CONTRACTS.md`, `docs/WORKSTREAMS.md`, and `conferge/core/schemas.py` before editing. Use only this branch and worktree. **Never modify** `conferge/core/`, `pyproject.toml`, `Makefile`, shared documentation, CI or another window's files. Need shared change? Document exact proposed change and let window 00 handle it. Do not automatically merge a PR; main is integrated by window 00 after green CI.

**Demo anchor:** GitHub Universe 2026, Fort Mason, San Francisco, 28–29 October; NYC→SF Oct 27–30. Sources must be attributable, timezone-aware, and tagged `live`, `cached` or `fixture`. Never invent times, prices, people attendance, accommodation availability or conference affiliations. Fixtures are always explicit; errors/partial pagination must return degraded/failed status. Only Bright Data and FalkorDB are target sponsor technologies.

## Assignment

Build minimal FastAPI app and single-page modern interface for scripted demo: input preset GitHub Universe founder goal and NYC Oct 27–30, event cards, opportunity/person graph visual (Cytoscape or simple SVG), ordered daily itinerary, source/status badges (`live`, `cached`, `fixture`). Provide lightweight endpoints that can read JSON fixtures initially and later accept injected provider/graph implementations. No modification to `core` or shared dependencies. Prefer zero build step plain HTML/JS/CSS.

## Deliverables

- `conferge/api/app.py` and independently owned `static/` frontend; `/health` and versioned `/api/` JSON endpoints.
- Offline FastAPI TestClient tests and probe of fixture demo.

## Acceptance

- UI never labels demo records live unless source says live; graceful missing-provider behavior.
- Visible FalkorDB relationship evidence and Bright Data provenance when integrations land.

Work autonomously with mocked provider responses if credentials are unavailable. Run `make check`, produce `make probe-api` (if a probe is relevant) with a markdown diagnostic, commit small changes and open a PR into main. In the PR state what works live, what is fixture, blockers, tested cases, and exactly which files were edited.
