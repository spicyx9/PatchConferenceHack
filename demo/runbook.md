# Conferge 3-minute demo runbook (offline fixture world)

Stage: Patch the Conference, 2026-10-24, 17:30 to 18:30 slot (2 to 3 minutes per team).
Story: a fictional founder flies New York -> San Francisco 2026-10-27 to 2026-10-30 for
GitHub Universe 2026 (Fort Mason Center, 2026-10-28/29), budget 2500 USD.

**Data honesty, read first.** Everything below comes from `conferge/demo` with
`source_mode=fixture`: fictional personas (bio: "Fictional demo persona. Not a real person;
attendance is simulated."), synthetic sessions, side events and venues, simulated prices
(flights `price_status=sandbox`, lodging `quoted_total` or `indicative`, never
`verified_bookable`), URLs on `demo.conferge.invalid`. Only the anchor (GitHub Universe 2026,
Fort Mason Center, 2026-10-28/29) comes from `docs/knowledge/`, and it is not live-verified
here. Never present fixture as live. The fixture badge stays visible on every screen. Live
Bright Data collection, if keys arrive on 2026-10-24 morning, is shown only through other
windows' connectors and `make probe-<slug>`, never through this replay.

## Roles

- Speaker (S): talks, never touches the keyboard.
- Driver (D): clicks and types. Solo team: same person, keep the replay pre-opened.
- Screen: w12 UI if merged (`conferge/api`, `static/`), else the CLI replay
  `uv run python -m conferge.demo` in a large-font terminal. FalkorDB browser
  (http://localhost:3000) in a second tab.

## Pre-show setup (T-30 min)

```bash
cd <repo checkout on latest main>
git pull --ff-only
uv sync --group dev
make up                                        # FalkorDB docker, ports 6379 and 3000
uv run python scripts/gen_fixtures.py          # writes fixtures/demo.json
uv run python scripts/gen_fixtures.py --check  # must exit 0 (fixture not stale)
make check                                     # lint + tests green
make probe-demo                                # writes probes/demo.md, read it
uv run python -m conferge.demo                 # rehearse the scripted replay once
uv run python -c "import json; from conferge.demo import replay; print(json.dumps(replay(), indent=1))" > /tmp/replay.json
```

Keep `/tmp/replay.json` open in an editor tab as a last-resort screen. Then run
`demo/judge-checklist.md` top to bottom.

## Timed script

### 0:00 Problem (S speaks, D shows title screen with fixture badge)

S: "Two days of conference, dozens of side events, thousands of people, and you fly home with
four business cards. Conferge starts from your goal, not from the agenda."

### 0:20 Goal input and weighted goals (D types or pastes the goal)

- Goal text: "Founder of an AI dev tool going to GitHub Universe to meet seed investors,
  AI agent founders and Copilot PMs."
- Screen: weighted goals `goal-seed-investors` 0.45, `goal-agent-founders` 0.35,
  `goal-copilot-pms` 0.20; discovery counts 10 events, 14 people, 8 companies, 3 stays,
  3 flights, all `source_mode=fixture`.
- S: "This world is a deterministic fixture so the demo cannot break; the badge says so."

### 0:50 Top people with graph path (D scrolls the top 10, opens one path)

- Screen: top 10 from `top_people`. Read the first three:
  1. `p-inv-ada` (Ada Lanternwood, fictional Partner), score 45.0, speaks at
     `evt-s-funding-devtools` "Funding Developer Tools in 2027", 2026-10-29 15:00 PT.
  2. `p-inv-bram` (Bram Quillfeather), 36.0, hosts `evt-side-agents-after-hours`.
  3. `p-inv-cleo` (Cleo Marrowind), 36.0, hosts `evt-side-devtools-dinner`.
- Path for Ada: `Goal goal-seed-investors -> ABOUT -> Topic "ai agents" -> SERVES_GOAL ->
  Person p-inv-ada -> SPEAKS_AT -> Event evt-s-funding-devtools`.
- If the graph window has loaded this world through `GraphStore`, D switches to the FalkorDB
  browser and shows the same path; otherwise show the `path` array from the replay. Do not
  claim a live multi-hop query if none was run.
- S (FalkorDB criterion): "Every recommendation is an explainable multi-hop path in the
  graph, Goal to Topic to Person to Event, so you see why, not just who."

### 1:30 Plan and anti-FOMO clash (D opens the day-by-day plan)

- Screen: 8 planned events, total value 339.0, from Pre-Universe Builders Meetup
  (2026-10-27 18:30 PT) to Seed Office Hours (2026-10-29 18:00 PT).
- Clash on 2026-10-28 evening: Agents After Hours (18:30 to 21:30, value 69.0, hosts
  Bram Quillfeather and Hale Driftmoor) vs Devtools Founders Dinner (19:00 to 21:30, value
  62.0). Venues 1.36 km apart (synthetic coordinates).
- Verdict: Agents After Hours wins. You miss `p-inv-cleo` (Cleo Marrowind) and `p-pm-kael`
  (Kael Windmere), 2 goal-matched people.
- S: "It picks one, tells you why in numbers, and tells you exactly who you miss."

### 2:00 Travel (D opens travel panel, fixture label visible)

- Chosen flight `flt-ewr-sfo-noon`: EWR 12:00 ET -> SFO 15:20 PT on 2026-10-27, 468.90 USD,
  `price_status=sandbox`, carrier "Fixture Air (fictional)".
- Rejected `flt-lga-oak-evening` (401.15 USD, cheaper): lands OAK 20:30 PT, too late for the
  18:30 meetup with the 2-hour arrival buffer. `flt-jfk-sfo-morning` (512.40 USD) arrives in
  time but costs more.
- Stay `stay-marina-inn` "Marina Courtyard Inn (synthetic)", 900 m from Fort Mason,
  897.00 USD for 3 nights, `price_status=quoted_total` (not verified bookable).
- Simulated total 1365.90 USD vs budget 2500 USD.
- Proactive suggestion: "Arrive 2026-10-27 to make Pre-Universe Builders Meetup at
  2026-10-27T18:30:00-07:00."
- S: "Simulated fares and room totals, labelled as such. With live keys, the stay and
  side-event connectors show real collected_at timestamps instead."

### 2:30 Live replanning (D clicks "simulate a change", or the CLI step)

- Change `scenario-cancel-clash-winner`: `evt-side-agents-after-hours` becomes `cancelled`
  (fixture simulated cancellation).
- Diff: removed `evt-side-agents-after-hours`, added `evt-side-devtools-dinner`, 7 events kept;
  value 339.0 -> 332.0; no clash left.
- Ranking change: `p-inv-cleo` rises to #2; `p-inv-bram` drops from #2 to #8 (his only event
  is cancelled, score halved); `p-pm-kael` enters at #10; `p-fnd-hale` leaves the top 10.
- S (Bright Data criterion): "This world is fixture; the live part is Bright Data collecting
  hard-to-get pages that block curl, with fresh collected_at, and we show it only through our
  connector probes." Say this sentence only if a probe ran live today; if keys are absent,
  say "Bright Data connectors are built, live collection is not shown today."
- There is no "met" button in the offline replay. Show it only if w12 UI with graph memory
  is merged and tested.

### 2:50 Reuse (S speaks, D shows the graph overview)

S (FalkorDB criterion): "The graph is the memory: people, events, topics and goals live in
FalkorDB, written only through GraphStore MERGE, so the next conference and every agent start
from shared state instead of from zero."
Note: the offline replay itself does not write to FalkorDB. Claim persistence on stage only if
the graph window's loader has written this world and you can show it at localhost:3000.

## Fallback if wifi or an API fails

1. The replay needs no network and no keys: switch to the terminal and run
   `uv run python -m conferge.demo`, narrate the same timeline.
2. If the terminal fails: show `/tmp/replay.json` or `fixtures/demo.json` in the editor.
3. If FalkorDB is down: show the `path` arrays from the replay; say "graph view offline".
4. If a live Bright Data probe fails on stage: say so, show its `status=degraded/failed`
   output, do not swap in fixture silently.
5. Last resort: the manually recorded backup video (no `make record` target exists; record it
   before the event). Announce it as a recording.
