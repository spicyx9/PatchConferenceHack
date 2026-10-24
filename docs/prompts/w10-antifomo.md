# Conferge — Window 10 / Anti-FOMO and replanning

**Repo:** spicyx9/HTest. **Branch:** `w10-antifomo`. **Owner:** `conferge/agents/antifomo/ and conferge/agents/replanner/` plus matching `tests/antifomo/`, `scripts/probes/antifomo.py`, `fixtures/antifomo.json` and `probes/antifomo.md` only.

Read `CLAUDE.md`, `docs/CONTRACTS.md`, `docs/WORKSTREAMS.md`, and `conferge/core/schemas.py` before editing. Use only this branch and worktree. **Never modify** `conferge/core/`, `pyproject.toml`, `Makefile`, shared documentation, CI or another window's files. Need shared change? Document exact proposed change and let window 00 handle it. Do not automatically merge a PR; main is integrated by window 00 after green CI.

**Demo anchor:** GitHub Universe 2026, Fort Mason, San Francisco, 28–29 October; NYC→SF Oct 27–30. Sources must be attributable, timezone-aware, and tagged `live`, `cached` or `fixture`. Never invent times, prices, people attendance, accommodation availability or conference affiliations. Fixtures are always explicit; errors/partial pagination must return degraded/failed status. Only Bright Data and FalkorDB are target sponsor technologies.

## Assignment

Implement conflict-aware selection of events with bounded daily time slots, travel buffers, fixed appointments and transparent trade-off explanations. Inspired by Pathfinder but do not import code absent permissions. Deterministic optimization first; ability to simulate an event cancellation and propose a minimally changed agenda. Use fixture data until graph/official schedule is ready.

## Deliverables

- Pure planner/replanner functions plus Agent.run adaptor.
- Offline tests for overlaps, travel buffer, cancellation and minimal change.
- Probe with before/after schedule and why each decision changed.

## Acceptance

- No overlapping confirmed events in selected agenda.
- Never claim a session available when registration evidence absent.

Work autonomously with mocked provider responses if credentials are unavailable. Run `make check`, produce `make probe-antifomo` (if a probe is relevant) with a markdown diagnostic, commit small changes and open a PR into main. In the PR state what works live, what is fixture, blockers, tested cases, and exactly which files were edited.
