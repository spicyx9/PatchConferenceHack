# Conferge — Window 01 / Luma + Partiful discovery

**Repo:** spicyx9/PatchConferenceHack. **Branch:** `w01-luma-partiful`. **Owner:** `conferge/events/luma/ and conferge/events/partiful/` plus matching `tests/luma/`, `scripts/probes/luma.py`, `fixtures/luma.json` and `probes/luma.md` only.

Read `CLAUDE.md`, `docs/CONTRACTS.md`, `docs/WORKSTREAMS.md`, and `conferge/core/schemas.py` before editing. Use only this branch and worktree. **Never modify** `conferge/core/`, `pyproject.toml`, `Makefile`, shared documentation, CI or another window's files. Need shared change? Document exact proposed change and let window 00 handle it. Do not automatically merge a PR; main is integrated by window 00 after green CI.

**Demo anchor:** GitHub Universe 2026, Fort Mason, San Francisco, 28–29 October; NYC→SF Oct 27–30. Sources must be attributable, timezone-aware, and tagged `live`, `cached` or `fixture`. Never invent times, prices, people attendance, accommodation availability or conference affiliations. Fixtures are always explicit; errors/partial pagination must return degraded/failed status. Only Bright Data and FalkorDB are target sponsor technologies.

## Assignment

Implement two independent Source adapters. Luma: public geographic discovery, correct `pagination_cursor`, has_more, seen-cursor/ID loop detection, bounded pages, category filters, SF date window, source URL, timezone and host IDs. Partiful: public Explore regional page, dynamically discover buildId, combine trending/sections/feed, fetch details only when legitimately public; do not claim full regional completeness. Nonofficial endpoints may change; capture schema drift; no guest-list access.

## Deliverables

- `LumaSource` and `PartifulSource` with `discover(DiscoveryQuery)->DiscoveryResult` and `fetch_details(SourceRef)->SourceRecord`.
- Offline tests for cursor stuck, zero page, changed JSON schema, duplicate IDs and timezone.
- Probe for public SF Oct 27–30 results with links, counts and termination status.

## Acceptance

- Luma can stop as exhausted only on actual `has_more=false`; repeated cursor is degraded.
- Partiful partial feed is labelled degraded when completeness unknown.
- SourceRecord payload and timestamps preserved.

Work autonomously with mocked provider responses if credentials are unavailable. Run `make check`, produce `make probe-luma` (if a probe is relevant) with a markdown diagnostic, commit small changes and open a PR into main. In the PR state what works live, what is fixture, blockers, tested cases, and exactly which files were edited.
