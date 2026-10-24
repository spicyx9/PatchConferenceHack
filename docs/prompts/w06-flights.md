# Conferge — Window 06 / Flights / travel to conference

**Repo:** spicyx9/HTest. **Branch:** `w06-flights`. **Owner:** `conferge/flights/` plus matching `tests/flights/`, `scripts/probes/flights.py`, `fixtures/flights.json` and `probes/flights.md` only.

Read `CLAUDE.md`, `docs/CONTRACTS.md`, `docs/WORKSTREAMS.md`, and `conferge/core/schemas.py` before editing. Use only this branch and worktree. **Never modify** `conferge/core/`, `pyproject.toml`, `Makefile`, shared documentation, CI or another window's files. Need shared change? Document exact proposed change and let window 00 handle it. Do not automatically merge a PR; main is integrated by window 00 after green CI.

**Demo anchor:** GitHub Universe 2026, Fort Mason, San Francisco, 28–29 October; NYC→SF Oct 27–30. Sources must be attributable, timezone-aware, and tagged `live`, `cached` or `fixture`. Never invent times, prices, people attendance, accommodation availability or conference affiliations. Fixtures are always explicit; errors/partial pagination must return degraded/failed status. Only Bright Data and FalkorDB are target sponsor technologies.

## Assignment

Use Bright Data Google Flights structured scraper as primary; account for inconsistent discover-by-filters output by treating first response as candidate URL and calling collect-by-URL for `pricing/providers/legs`. Dataset ID to look up/validate: `gd_mhng7wen1rw0a3gvpf`. Expand NYC airports JFK/LGA/EWR and Bay arrival SFO/OAK/SJC only if each combination is relevant. Secondary SerpApi Google Flights (no_cache=true) if account key exists; optionally fast-flights diagnostic. Do not use discontinued Amadeus Self-Service.

## Deliverables

- Normalized `FlightOffer` with one roundtrip containing two slices, typed segment times and price as decimal string.
- Source evidence, observed time, connection uncertainty, link type.
- Offline tests for URL-only discovery, partial roundtrip, multiple airports, duplicate physical flights.

## Acceptance

- Never treat metasearch as ticket-guaranteed.
- A `booking_token` is not a booking URL.
- Fallback to fixtures only explicitly, marked fixture in returned models and probe.

Work autonomously with mocked provider responses if credentials are unavailable. Run `make check`, produce `make probe-flights` (if a probe is relevant) with a markdown diagnostic, commit small changes and open a PR into main. In the PR state what works live, what is fixture, blockers, tested cases, and exactly which files were edited.
