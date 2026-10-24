# Conferge — Window 15 / E2E integration harness

**Repo:** spicyx9/PatchConferenceHack. **Branch:** `w15-integration`. **Owner:** `conferge/integration/ and tests/integration/` plus matching `tests/integration/`, `scripts/probes/integration.py`, `fixtures/integration.json` and `probes/integration.md` only.

Read `CLAUDE.md`, `docs/CONTRACTS.md`, `docs/WORKSTREAMS.md`, and `conferge/core/schemas.py` before editing. Use only this branch and worktree. **Never modify** `conferge/core/`, `pyproject.toml`, `Makefile`, shared documentation, CI or another window's files. Need shared change? Document exact proposed change and let window 00 handle it. Do not automatically merge a PR; main is integrated by window 00 after green CI.

**Demo anchor:** GitHub Universe 2026, Fort Mason, San Francisco, 28–29 October; NYC→SF Oct 27–30. Sources must be attributable, timezone-aware, and tagged `live`, `cached` or `fixture`. Never invent times, prices, people attendance, accommodation availability or conference affiliations. Fixtures are always explicit; errors/partial pagination must return degraded/failed status. Only Bright Data and FalkorDB are target sponsor technologies.

## Assignment

Build read-only-from-feature-components smoke tests and an integration verifier. Avoid owning or editing any window's files. Validate full request→normalised sources→graph→planning→API flow when modules land and run fixture-only backup. File clear interface mismatch reports for window 00 to fix.

## Deliverables

- Integration smoke tests with no network dependencies, optional live probe flag, documented E2E pass/fail.

## Acceptance

- Core normalizers and graph tests remain green; no feature code edits.

Work autonomously with mocked provider responses if credentials are unavailable. Run `make check`, produce `make probe-integration` (if a probe is relevant) with a markdown diagnostic, commit small changes and open a PR into main. In the PR state what works live, what is fixture, blockers, tested cases, and exactly which files were edited.
