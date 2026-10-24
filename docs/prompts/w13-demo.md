# Conferge — Window 13 / Deterministic fallback demo

**Repo:** spicyx9/HTest. **Branch:** `w13-demo`. **Owner:** `conferge/demo/, scripts/gen_fixtures.py, and demo/` plus matching `tests/demo/`, `scripts/probes/demo.py`, `fixtures/demo.json` and `probes/demo.md` only.

Read `CLAUDE.md`, `docs/CONTRACTS.md`, `docs/WORKSTREAMS.md`, and `conferge/core/schemas.py` before editing. Use only this branch and worktree. **Never modify** `conferge/core/`, `pyproject.toml`, `Makefile`, shared documentation, CI or another window's files. Need shared change? Document exact proposed change and let window 00 handle it. Do not automatically merge a PR; main is integrated by window 00 after green CI.

**Demo anchor:** GitHub Universe 2026, Fort Mason, San Francisco, 28–29 October; NYC→SF Oct 27–30. Sources must be attributable, timezone-aware, and tagged `live`, `cached` or `fixture`. Never invent times, prices, people attendance, accommodation availability or conference affiliations. Fixtures are always explicit; errors/partial pagination must return degraded/failed status. Only Bright Data and FalkorDB are target sponsor technologies.

## Assignment

Own three-minute demo runbook and explicit fixture generation for the whole conference journey (NYC→SF Oct 27–30) with clear source labels. Prefer synthetic named people and clearly fictitious itineraries to avoid fabricating real people attendance. Write fixture output exclusively to `fixtures/demo.json` (not per-source fixtures). Simulate discovery, goal matching, one event clash and cancellation-triggered replanning.

## Deliverables

- Seed generator, `fixtures/demo.json`, and `demo/runbook.md`, `demo/judge-checklist.md`.
- Offline tests for deterministic replay, correct source-mode labels and no unstated real data.

## Acceptance

- Run end to end without external network or secrets.
- Present any simulated prices or attendance as fixture, never as real.

Work autonomously with mocked provider responses if credentials are unavailable. Run `make check`, produce `make probe-demo` (if a probe is relevant) with a markdown diagnostic, commit small changes and open a PR into main. In the PR state what works live, what is fixture, blockers, tested cases, and exactly which files were edited.
