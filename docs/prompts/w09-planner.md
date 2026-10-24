# Conferge — Window 09 / Reverse planner and networking agent

**Repo:** spicyx9/PatchConferenceHack. **Branch:** `w09-planner`. **Owner:** `conferge/agents/planner/ and conferge/agents/networking/` plus matching `tests/planner/`, `scripts/probes/planner.py`, `fixtures/planner.json` and `probes/planner.md` only.

Read `CLAUDE.md`, `docs/CONTRACTS.md`, `docs/WORKSTREAMS.md`, and `conferge/core/schemas.py` before editing. Use only this branch and worktree. **Never modify** `conferge/core/`, `pyproject.toml`, `Makefile`, shared documentation, CI or another window's files. Need shared change? Document exact proposed change and let window 00 handle it. Do not automatically merge a PR; main is integrated by window 00 after green CI.

**Demo anchor:** GitHub Universe 2026, Fort Mason, San Francisco, 28–29 October; NYC→SF Oct 27–30. Sources must be attributable, timezone-aware, and tagged `live`, `cached` or `fixture`. Never invent times, prices, people attendance, accommodation availability or conference affiliations. Fixtures are always explicit; errors/partial pagination must return degraded/failed status. Only Bright Data and FalkorDB are target sponsor technologies.

## Assignment

Create goal-oriented scoring/planning from `AgentContext`, independent of live provider availability. Explicit signal weights for seed investors, AI-agents founders and Copilot PMs, explained score per `Opportunity`. Begin with fixture Event/Person/Goal entities; use graph window 08 read interface only after available. Do not use the LLM to invent attendance or scheduling facts.

## Deliverables

- Agent implementation of `Agent.run(ctx)->AgentResult`, deterministic score and explanations.
- Offline tests of ranking stability, evidence and empty input.

## Acceptance

- Explain exactly why an opportunity is ranked high and which source fact supports it.
- Gracefully degrade when graph not yet integrated.

Work autonomously with mocked provider responses if credentials are unavailable. Run `make check`, produce `make probe-planner` (if a probe is relevant) with a markdown diagnostic, commit small changes and open a PR into main. In the PR state what works live, what is fixture, blockers, tested cases, and exactly which files were edited.
