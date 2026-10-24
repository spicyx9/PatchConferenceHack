# Conferge — Window 03 / Official GitHub Universe

**Repo:** spicyx9/HTest. **Branch:** `w03-official`. **Owner:** `conferge/events/official/` plus matching `tests/official/`, `scripts/probes/official.py`, `fixtures/official.json` and `probes/official.md` only.

Read `CLAUDE.md`, `docs/CONTRACTS.md`, `docs/WORKSTREAMS.md`, and `conferge/core/schemas.py` before editing. Use only this branch and worktree. **Never modify** `conferge/core/`, `pyproject.toml`, `Makefile`, shared documentation, CI or another window's files. Need shared change? Document exact proposed change and let window 00 handle it. Do not automatically merge a PR; main is integrated by window 00 after green CI.

**Demo anchor:** GitHub Universe 2026, Fort Mason, San Francisco, 28–29 October; NYC→SF Oct 27–30. Sources must be attributable, timezone-aware, and tagged `live`, `cached` or `fixture`. Never invent times, prices, people attendance, accommodation availability or conference affiliations. Fixtures are always explicit; errors/partial pagination must return degraded/failed status. Only Bright Data and FalkorDB are target sponsor technologies.

## Assignment

Discover the actual publicly accessible GitHub Universe 2026 event catalog, official talks, speakers, sponsors, rooms, and published times. Prefer official feeds/embedded JSON/ICS/Sessionize/Sched where available; use shared BrightDataClient unlocker only if necessary. Avoid assuming authenticated portal content is public. Classify official sessions distinctly from third-party side events.

## Deliverables

- `OfficialConferenceSource` discover/detail adapters and normalizers to core Event, Person, Company, Conference.
- Offline tests for missing speaker, ambiguous track and malformed timezone.
- Fixture for schema tests; optional live probe with actual source URLs.

## Acceptance

- `Person.participation=confirmed_speaker` must be supported by an official source and never imply unrelated-party attendance.
- Unverified sessions stay candidate, no fake speaker data.
- No fabricated session times.

Work autonomously with mocked provider responses if credentials are unavailable. Run `make check`, produce `make probe-official` (if a probe is relevant) with a markdown diagnostic, commit small changes and open a PR into main. In the PR state what works live, what is fixture, blockers, tested cases, and exactly which files were edited.
