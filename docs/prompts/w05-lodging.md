# Conferge — Window 05 / Lodging / stays

**Repo:** spicyx9/HTest. **Branch:** `w05-lodging`. **Owner:** `conferge/lodging/` plus matching `tests/lodging/`, `scripts/probes/lodging.py`, `fixtures/lodging.json` and `probes/lodging.md` only.

Read `CLAUDE.md`, `docs/CONTRACTS.md`, `docs/WORKSTREAMS.md`, and `conferge/core/schemas.py` before editing. Use only this branch and worktree. **Never modify** `conferge/core/`, `pyproject.toml`, `Makefile`, shared documentation, CI or another window's files. Need shared change? Document exact proposed change and let window 00 handle it. Do not automatically merge a PR; main is integrated by window 00 after green CI.

**Demo anchor:** GitHub Universe 2026, Fort Mason, San Francisco, 28–29 October; NYC→SF Oct 27–30. Sources must be attributable, timezone-aware, and tagged `live`, `cached` or `fixture`. Never invent times, prices, people attendance, accommodation availability or conference affiliations. Fixtures are always explicit; errors/partial pagination must return degraded/failed status. Only Bright Data and FalkorDB are target sponsor technologies.

## Assignment

Search Booking and Google Hotels through Bright Data's structured scraper datasets (discover method and schema must be verified with actual samples, not assumed). Use pyairbnb (MIT) for Airbnb search with exact check-in/check-out and guests, and Bright Data Airbnb fallback if possible. For New York visitor staying SF Oct 27–30 near Fort Mason (not Moscone), distinguish hotel entity from offers. Work with existing core.Lodging model and optional adapter-specific detail classes.

## Deliverables

- Booking/GoogleHotels/Airbnb providers with exact query-date semantics.
- Source-independent lodging normalization; total stay vs nightly rate, taxes/fees unknown if missing; evidence and booking link.
- Offline test suite and probe showing quote status and source freshness.

## Acceptance

- `verified_bookable` only with exact-occupancy/date available inventory, total price and deeplink.
- No price=0 fallback, no fake tax or resort fee.
- Unknown or indicative offers labelled, never falsely bookable.

Work autonomously with mocked provider responses if credentials are unavailable. Run `make check`, produce `make probe-lodging` (if a probe is relevant) with a markdown diagnostic, commit small changes and open a PR into main. In the PR state what works live, what is fixture, blockers, tested cases, and exactly which files were edited.
