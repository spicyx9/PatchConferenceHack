# Conferge — Patch the Conference 2026

Conferge optimises a professional trip around a conference, based on measurable networking goals. Hackathon tracks: **Bright Data** (acquisition) and **FalkorDB** (opportunity graph).

**Demo anchor:** GitHub Universe 2026, October 28–29, Fort Mason, San Francisco. Fictional traveller: 1 adult, New York → San Francisco, October 27–30; goals: seed investors, AI-agent founders, Copilot PMs.

## Window 0 — shared foundation

This repository has **one shared Python package** (`conferge/`). Interfaces in `conferge/core/` are frozen before feature work starts. Each development window owns a separate directory and branch. See [CLAUDE.md](CLAUDE.md), [contracts](docs/CONTRACTS.md), and [workstreams](docs/WORKSTREAMS.md).

### Setup

```bash
uv sync --group dev
uv run pytest -q
uv run ruff check .
docker compose up -d falkordb
```

`make check` runs lint and tests; `make probe-luma` will call the Luma probe **after** window 1 creates it. Configuration goes in `.env` (never commit credentials). See `.env.example`.

**Data integrity:** every record carries source provenance, collection time, and `source_mode` (`live`, `cached`, or `fixture`). Real API errors must not silently become fictional successes. All prices and attendance claims must be evidenced.
