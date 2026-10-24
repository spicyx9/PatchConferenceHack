# Conferge — Window 07 / Public people enrichment

**Repo:** spicyx9/PatchConferenceHack. **Branch:** `w07-people`. **Owner:** `conferge/people/` plus matching `tests/people/`, `scripts/probes/people.py`, `fixtures/people.json` and `probes/people.md` only.

Read `CLAUDE.md`, `docs/CONTRACTS.md`, `docs/WORKSTREAMS.md`, and `conferge/core/schemas.py` before editing. Use only this branch and worktree. **Never modify** `conferge/core/`, `pyproject.toml`, `Makefile`, shared documentation, CI or another window's files. Need shared change? Document exact proposed change and let window 00 handle it. Do not automatically merge a PR; main is integrated by window 00 after green CI.

**Demo anchor:** GitHub Universe 2026, Fort Mason, San Francisco, 28–29 October; NYC→SF Oct 27–30. Sources must be attributable, timezone-aware, and tagged `live`, `cached` or `fixture`. Never invent times, prices, people attendance, accommodation availability or conference affiliations. Fixtures are always explicit; errors/partial pagination must return degraded/failed status. Only Bright Data and FalkorDB are target sponsor technologies.

## Assignment

Identify public speakers, hosts and relevant professional profiles; source each identity match (name/company/profile), use Bright Data SERP and available structured public data, never access private attendee/guest rosters. Implement two-stage ranking: deterministic topic/role shortlist then optional LLM scoring of small capped set. Provide networking reason and suggested conversation opener, clearly distinguish relevant candidate from actual attendance.

## Deliverables

- People entities with evidence/participation confidence; dedup and enrichment.
- Rule-based ranking with optional injected scoring adapter; offline tests.
- Mark real vs fixture explicitly.

## Acceptance

- No guessed LinkedIn URLs or emails, no `ATTENDS_CONFIRMED` without evidence.
- Reliable offline behavior without LLM key.

Work autonomously with mocked provider responses if credentials are unavailable. Run `make check`, produce `make probe-people` (if a probe is relevant) with a markdown diagnostic, commit small changes and open a PR into main. In the PR state what works live, what is fixture, blockers, tested cases, and exactly which files were edited.
