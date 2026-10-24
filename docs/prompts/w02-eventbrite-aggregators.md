# Conferge — Window 02 / Eventbrite + aggregators

**Repo:** spicyx9/HTest. **Branch:** `w02-eventbrite-aggregators`. **Owner:** `conferge/events/eventbrite/ and conferge/events/aggregators/` plus matching `tests/eventbrite-aggregators/`, `scripts/probes/eventbrite-aggregators.py`, `fixtures/eventbrite-aggregators.json` and `probes/eventbrite-aggregators.md` only.

Read `CLAUDE.md`, `docs/CONTRACTS.md`, `docs/WORKSTREAMS.md`, and `conferge/core/schemas.py` before editing. Use only this branch and worktree. **Never modify** `conferge/core/`, `pyproject.toml`, `Makefile`, shared documentation, CI or another window's files. Need shared change? Document exact proposed change and let window 00 handle it. Do not automatically merge a PR; main is integrated by window 00 after green CI.

**Demo anchor:** GitHub Universe 2026, Fort Mason, San Francisco, 28–29 October; NYC→SF Oct 27–30. Sources must be attributable, timezone-aware, and tagged `live`, `cached` or `fixture`. Never invent times, prices, people attendance, accommodation availability or conference affiliations. Fixtures are always explicit; errors/partial pagination must return degraded/failed status. Only Bright Data and FalkorDB are target sponsor technologies.

## Assignment

Build Eventbrite event discovery and conference-parties/organizer-site extraction. Internal destination search may need session/CSRF; prefer documented source access/Bright Data where practical. Handle ~950 result pagination ceilings with date partitions and explicit `page_cap`, never silently report complete. Do not copy unlicensed e-Reese code; independently implement the documented algorithms. No speaker/official catalog work (window 03).

## Deliverables

- Source adapters and parser for event listings with organizer URL, start and end datetime, venue and source IDs.
- Unit tests for date splitting, zero results, failed browser context and changing page layout.
- Probe storing raw/unique counts and all incomplete-window reasons.

## Acceptance

- Partial Eventbrite results remain usable but status=degraded.
- A returned page without valid dates is not assigned today's date.
- All cross-source merges are deferred to integration; never drop provenance.

Work autonomously with mocked provider responses if credentials are unavailable. Run `make check`, produce `make probe-eventbrite-aggregators` (if a probe is relevant) with a markdown diagnostic, commit small changes and open a PR into main. In the PR state what works live, what is fixture, blockers, tested cases, and exactly which files were edited.
