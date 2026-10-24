# Conferge — Window 11 / Ground travel (optional)

**Repo:** spicyx9/PatchConferenceHack. **Branch:** `w11-travel`. **Owner:** `conferge/travel/` plus matching `tests/travel/`, `scripts/probes/travel.py`, `fixtures/travel.json` and `probes/travel.md` only.

Read `CLAUDE.md`, `docs/CONTRACTS.md`, `docs/WORKSTREAMS.md`, and `conferge/core/schemas.py` before editing. Use only this branch and worktree. **Never modify** `conferge/core/`, `pyproject.toml`, `Makefile`, shared documentation, CI or another window's files. Need shared change? Document exact proposed change and let window 00 handle it. Do not automatically merge a PR; main is integrated by window 00 after green CI.

**Demo anchor:** GitHub Universe 2026, Fort Mason, San Francisco, 28–29 October; NYC→SF Oct 27–30. Sources must be attributable, timezone-aware, and tagged `live`, `cached` or `fixture`. Never invent times, prices, people attendance, accommodation availability or conference affiliations. Fixtures are always explicit; errors/partial pagination must return degraded/failed status. Only Bright Data and FalkorDB are target sponsor technologies.

## Assignment

Optional after critical demo paths: estimate airport→Fort Mason→hotel transfers only where a trusted routing service or data is available. Keep ground travel cost/time `unknown` when no source; no Gmail integration in MVP. Output provider-neutral routing candidate data without core edits.

## Deliverables

- Pluggable route provider, mock tests, labelled route cost/duration evidence.

## Acceptance

- No invented transit time or Uber fare. Never delay core demo.

Work autonomously with mocked provider responses if credentials are unavailable. Run `make check`, produce `make probe-travel` (if a probe is relevant) with a markdown diagnostic, commit small changes and open a PR into main. In the PR state what works live, what is fixture, blockers, tested cases, and exactly which files were edited.
