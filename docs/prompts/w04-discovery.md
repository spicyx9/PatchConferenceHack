# Conferge — Window 04 / Bright Data discovery

**Repo:** spicyx9/PatchConferenceHack. **Branch:** `w04-discovery`. **Owner:** `conferge/events/discovery/` plus matching `tests/discovery/`, `scripts/probes/discovery.py`, `fixtures/discovery.json` and `probes/discovery.md` only.

Read `CLAUDE.md`, `docs/CONTRACTS.md`, `docs/WORKSTREAMS.md`, and `conferge/core/schemas.py` before editing. Use only this branch and worktree. **Never modify** `conferge/core/`, `pyproject.toml`, `Makefile`, shared documentation, CI or another window's files. Need shared change? Document exact proposed change and let window 00 handle it. Do not automatically merge a PR; main is integrated by window 00 after green CI.

**Demo anchor:** GitHub Universe 2026, Fort Mason, San Francisco, 28–29 October; NYC→SF Oct 27–30. Sources must be attributable, timezone-aware, and tagged `live`, `cached` or `fixture`. Never invent times, prices, people attendance, accommodation availability or conference affiliations. Fixtures are always explicit; errors/partial pagination must return degraded/failed status. Only Bright Data and FalkorDB are target sponsor technologies.

## Assignment

Build goal- and conference-aware search queries across official sites, Luma, Partiful, Eventbrite, independent meetup pages, and sponsors for Oct 26–31 in San Francisco. Use only shared `BrightDataClient.serp`, `unlock`, and structured datasets if accessible. The SERP returns candidate URLs, not verified Events. Route candidate URLs by domain for downstream adapters and retain reason for discovery; support bounded concurrency, duplicate URL suppression, modest costs and no new global API client.

## Deliverables

- Query generator / `SerpDiscoverySource` with SourceRecord provenance and confidence tagged as discovery candidate.
- Domain router with platform and generic site classification.
- Offline HTTP-mock tests plus readable probe showing links and mode.

## Acceptance

- No SERP snippet becomes a confirmed event automatically.
- Network errors do not silently become fixtures.
- Query variants include conference name, sponsor/host and venue/date without conference keywords.

Work autonomously with mocked provider responses if credentials are unavailable. Run `make check`, produce `make probe-discovery` (if a probe is relevant) with a markdown diagnostic, commit small changes and open a PR into main. In the PR state what works live, what is fixture, blockers, tested cases, and exactly which files were edited.
