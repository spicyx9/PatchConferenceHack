# Judge checklist (run before going on stage, 2026-10-24)

## Environment

- [ ] On latest `main`, `uv sync --group dev` done.
- [ ] `make up` ran; `docker compose ps` shows `falkordb` healthy.
- [ ] FalkorDB browser opens at http://localhost:3000 (port 3000, bound to 127.0.0.1).
- [ ] `uv run python scripts/gen_fixtures.py` ran, then
      `uv run python scripts/gen_fixtures.py --check` exits 0 (fixtures/demo.json not stale).
- [ ] `make check` green (lint + tests).
- [ ] `make probe-demo` ran and `probes/demo.md` was read: every record is `fixture`, no
      record claims `live` or `cached`.
- [ ] `uv run python -m conferge.demo` rehearsed once end to end, offline.

## Keys and what they imply

- [ ] Bright Data key present? If yes: run the source windows' `make probe-<slug>` and keep a
      fresh probe report open; only those records may be called live, with `collected_at`.
- [ ] If absent: nothing shown is live. Say "fixture" out loud; do not mention live collection
      as part of the demo.
- [ ] OpenAI key present? If absent, the goal weights (0.45/0.35/0.20) come from the fixture,
      not from live extraction; do not claim the LLM extracted them.
- [ ] No key, token or `.env` content visible on any screen or terminal history.

## Screens

- [ ] Browser fullscreen, zoom readable from the back of the room, notifications off.
- [ ] If w12 UI is merged: it is open on the demo user. If not: terminal with large font ready
      for the CLI replay.
- [ ] Fixture badges visible on every panel (people, plan, travel, replanning).
- [ ] FalkorDB browser tab open (graph view only if the world is loaded through `GraphStore`).
- [ ] Qodo PR open in a tab, with 2 or 3 review-driven fixes ready to point at.
- [ ] Backup video recorded manually beforehand and playable offline (no `make record` target).
- [ ] `/tmp/replay.json` open in an editor as last-resort screen.

## Claims we must NOT make

- [ ] No real attendance: every person is a fictional persona; "confirmed" means confirmed
      inside the fixture world only.
- [ ] No real prices: fares are `sandbox`, room totals are `quoted_total` or `indicative`,
      never `verified_bookable`, never "bookable now".
- [ ] No confirmed side-event affiliation: side events are `conference_relation=candidate`,
      not official GitHub Universe events.
- [ ] A speaker is not an attendee elsewhere: speaking at a session does not mean the person
      attends any side event.
- [ ] No real venues, rooms or walking times for synthetic venues; distances come from
      synthetic coordinates.
- [ ] The sessions are not the official Universe program; only the anchor (GitHub Universe
      2026, Fort Mason Center, 2026-10-28/29) comes from the knowledge base, not live-verified.
- [ ] No "met" button or cross-session memory claim unless it is merged and shown working.
- [ ] Never call fixture output "live", and never hide the fixture badge.
