# Probe: antifomo (window 10)

- Probe run at: 2026-10-24T07:34:38+00:00
- Source mode: **fixture** (synthetic events and people, labelled `[Fixture]`)
- Fixture: `fixtures/antifomo.json`, collected_at 2026-10-24T12:00:00-07:00
- Records: 13 events, 8 people, 3 goals (raw = unique, no dedup needed)
- Status: ok / termination: not_applicable (no network collection in this window)
- Graph: FalkorDB 127.0.0.1:6379 reachable; writes skipped (set ANTIFOMO_PROBE_GRAPH_WRITE=1 to record scenario changes)
- Live behaviour: none claimed. Agents consume normalized data; live quality depends on windows 01-09.

## Baseline agenda

| Day | Time | Event | U | Travel from prev | Registration | Targets |
|---|---|---|---|---|---|---|
| 2026-10-28 | 09:00-10:30 | [Fixture] Opening keynote (simulated time) | 52.5 | - | registration_link_found | p-pm-fay |
| 2026-10-28 | 11:00-11:45 | [Fixture] Building agents with MCP | 53.0 | 5 min (same_venue) | registration_link_found | p-fdr-dev |
| 2026-10-28 | 12:30-13:30 | [Fixture] Copilot PM lunch roundtable | 36.1 | 10 min (haversine) | registration_link_found | p-pm-gus |
| 2026-10-28 | 14:00-16:00 | [Fixture] Agent evals workshop | 28.6 | 10 min (haversine) | no_registration_evidence | - |
| 2026-10-28 | 18:00-20:00 | [Fixture] Seed Investors Happy Hour | 64.5 | 10 min (haversine) | registration_link_found | p-inv-ben, p-inv-hana (probable) |
| 2026-10-28 | 21:30-23:30 | [Fixture] Late after party | 21.2 | 23 min (haversine) | no_registration_evidence | p-fdr-eli |
| 2026-10-29 | 10:00-10:45 | [Fixture] Copilot extensibility deep dive | 56.7 | - | registration_link_found | p-pm-fay, p-pm-gus |
| 2026-10-29 | 13:00-14:00 | [Fixture] Investor office hours | 49.4 | 26 min (haversine) | registration_link_found | p-inv-cleo |
| 2026-10-29 | 19:00-21:00 | [Fixture] Stealth founders dinner | 26.2 | 20 min (unknown_default) | no_registration_evidence | - |

Total utility 388.27, known event spend 25 USD, unknown price for: ev-28-eval-workshop, ev-28-keynote, ev-28-late-party, ev-28-mcp-talk, ev-29-copilot-talk, ev-29-stealth-dinner.

### Rationale

- KEEP Wed 28 Oct 09:00 [Fixture] Opening keynote (simulated time) (U=52.5): confirmed targets: Fay Fixture (fictional); entry price unknown; goal topics: ai agents, copilot
- KEEP Wed 28 Oct 11:00 [Fixture] Building agents with MCP (U=53.0, 5 min from previous (same_venue)): confirmed targets: Dev Fixture (fictional); entry price unknown; goal topics: ai agents, mcp
- KEEP Wed 28 Oct 12:30 [Fixture] Copilot PM lunch roundtable (U=36.1, 10 min from previous (haversine)): confirmed targets: Gus Fixture (fictional); goal topics: copilot
- KEEP Wed 28 Oct 14:00 [Fixture] Agent evals workshop (U=28.6, 10 min from previous (haversine)): entry price unknown; goal topics: ai agents
-   warning: no registration evidence: a seat is not guaranteed
- KEEP Wed 28 Oct 18:00 [Fixture] Seed Investors Happy Hour (U=64.5, 10 min from previous (haversine)): confirmed targets: Ben Fixture (fictional); probable targets: Hana Fixture (fictional); goal topics: ai agents, developer tools
- KEEP Wed 28 Oct 21:30 [Fixture] Late after party (U=21.2, 23 min from previous (haversine)): confirmed targets: Eli Fixture (fictional); entry price unknown
-   warning: no registration evidence: a seat is not guaranteed
- KEEP Thu 29 Oct 10:00 [Fixture] Copilot extensibility deep dive (U=56.7): confirmed targets: Fay Fixture (fictional), Gus Fixture (fictional); entry price unknown; goal topics: copilot, developer tools
- KEEP Thu 29 Oct 13:00 [Fixture] Investor office hours (U=49.4, 26 min from previous (haversine)): confirmed targets: Cleo Fixture (fictional); goal topics: developer tools
- KEEP Thu 29 Oct 19:00 [Fixture] Stealth founders dinner (U=26.2, 20 min from previous (unknown_default)): entry price unknown; venue location imprecise; goal topics: ai agents
-   warning: no registration evidence: a seat is not guaranteed
-   warning: travel time assumed 20 min (venue location unknown)
- SKIP [Fixture] Devtools funding panel [conflict]: overlaps '[Fixture] Building agents with MCP'; utility 52.0 vs 53.0
- SKIP [Fixture] Agent Founders Mixer [conflict]: overlaps '[Fixture] Seed Investors Happy Hour' incl. 23 min travel; utility 48.5 vs 64.5
- SKIP [Fixture] Agent hack night (sold out) [unavailable]: event is sold out
- SKIP [Fixture] Rooftop meetup (time TBA) [time_unknown]: start or end time unknown; conflicts cannot be verified

## Anti-FOMO verdicts

- **ev-28-devtools-panel vs ev-28-mcp-talk** -> `ev-28-mcp-talk` (margin 1.03): Go to '[Fixture] Building agents with MCP' rather than '[Fixture] Devtools funding panel'. '[Fixture] Building agents with MCP' scores 53.0 vs 52.0. You miss confirmed: Ava Fixture (fictional); topics: developer tools.
- **ev-28-founders-mixer vs ev-28-investors-happy-hour** -> `ev-28-investors-happy-hour` (margin 16.03): Go to '[Fixture] Seed Investors Happy Hour' rather than '[Fixture] Agent Founders Mixer'. 1 probable target(s) vs 0; covers 2 target companies vs 1. You miss confirmed: Eli Fixture (fictional); topics: mcp. Catch up: Eli Fixture (fictional) also at '[Fixture] Late after party'.

## Replanning scenarios

### sold-out-evening: An Oct 28 evening side event becomes sold out

Change: `sold_out`; effects: '[Fixture] Seed Investors Happy Hour' is now sold out
Changes vs original: 2 (added 1, removed 1, moved 0)

Before:

| Day | Time | Event | U | Travel from prev | Registration | Targets |
|---|---|---|---|---|---|---|
| 2026-10-28 | 09:00-10:30 | [Fixture] Opening keynote (simulated time) | 52.5 | - | registration_link_found | p-pm-fay |
| 2026-10-28 | 11:00-11:45 | [Fixture] Building agents with MCP | 53.0 | 5 min (same_venue) | registration_link_found | p-fdr-dev |
| 2026-10-28 | 12:30-13:30 | [Fixture] Copilot PM lunch roundtable | 36.1 | 10 min (haversine) | registration_link_found | p-pm-gus |
| 2026-10-28 | 14:00-16:00 | [Fixture] Agent evals workshop | 28.6 | 10 min (haversine) | no_registration_evidence | - |
| 2026-10-28 | 18:00-20:00 | [Fixture] Seed Investors Happy Hour | 64.5 | 10 min (haversine) | registration_link_found | p-inv-ben, p-inv-hana (probable) |
| 2026-10-28 | 21:30-23:30 | [Fixture] Late after party | 21.2 | 23 min (haversine) | no_registration_evidence | p-fdr-eli |
| 2026-10-29 | 10:00-10:45 | [Fixture] Copilot extensibility deep dive | 56.7 | - | registration_link_found | p-pm-fay, p-pm-gus |
| 2026-10-29 | 13:00-14:00 | [Fixture] Investor office hours | 49.4 | 26 min (haversine) | registration_link_found | p-inv-cleo |
| 2026-10-29 | 19:00-21:00 | [Fixture] Stealth founders dinner | 26.2 | 20 min (unknown_default) | no_registration_evidence | - |

After:

| Day | Time | Event | U | Travel from prev | Registration | Targets |
|---|---|---|---|---|---|---|
| 2026-10-28 | 09:00-10:30 | [Fixture] Opening keynote (simulated time) | 52.5 | - | registration_link_found | p-pm-fay |
| 2026-10-28 | 11:00-11:45 | [Fixture] Building agents with MCP | 53.0 | 5 min (same_venue) | registration_link_found | p-fdr-dev |
| 2026-10-28 | 12:30-13:30 | [Fixture] Copilot PM lunch roundtable | 36.1 | 10 min (haversine) | registration_link_found | p-pm-gus |
| 2026-10-28 | 14:00-16:00 | [Fixture] Agent evals workshop | 28.6 | 10 min (haversine) | no_registration_evidence | - |
| 2026-10-28 | 18:30-21:00 | [Fixture] Agent Founders Mixer | 48.5 | 23 min (haversine) | registration_link_found | p-fdr-eli |
| 2026-10-28 | 21:30-23:30 | [Fixture] Late after party | 21.2 | 5 min (same_venue) | no_registration_evidence | p-fdr-eli |
| 2026-10-29 | 10:00-10:45 | [Fixture] Copilot extensibility deep dive | 56.7 | - | registration_link_found | p-pm-fay, p-pm-gus |
| 2026-10-29 | 13:00-14:00 | [Fixture] Investor office hours | 49.4 | 26 min (haversine) | registration_link_found | p-inv-cleo |
| 2026-10-29 | 19:00-21:00 | [Fixture] Stealth founders dinner | 26.2 | 20 min (unknown_default) | no_registration_evidence | - |

Why it changed:

- I replace '[Fixture] Seed Investors Happy Hour' with '[Fixture] Agent Founders Mixer'. '[Fixture] Seed Investors Happy Hour': event is sold out. '[Fixture] Agent Founders Mixer': confirmed targets: Eli Fixture (fictional); goal topics: ai agents, mcp. Travel adds 13 min.
- No fixed appointment touched.

### new-event-two-targets: A new event appears with two target people

Change: `new_event`; effects: new event '[Fixture] Agents x Seed breakfast'
Changes vs original: 2 (added 1, removed 1, moved 0)

Before:

| Day | Time | Event | U | Travel from prev | Registration | Targets |
|---|---|---|---|---|---|---|
| 2026-10-28 | 09:00-10:30 | [Fixture] Opening keynote (simulated time) | 52.5 | - | registration_link_found | p-pm-fay |
| 2026-10-28 | 11:00-11:45 | [Fixture] Building agents with MCP | 53.0 | 5 min (same_venue) | registration_link_found | p-fdr-dev |
| 2026-10-28 | 12:30-13:30 | [Fixture] Copilot PM lunch roundtable | 36.1 | 10 min (haversine) | registration_link_found | p-pm-gus |
| 2026-10-28 | 14:00-16:00 | [Fixture] Agent evals workshop | 28.6 | 10 min (haversine) | no_registration_evidence | - |
| 2026-10-28 | 18:00-20:00 | [Fixture] Seed Investors Happy Hour | 64.5 | 10 min (haversine) | registration_link_found | p-inv-ben, p-inv-hana (probable) |
| 2026-10-28 | 21:30-23:30 | [Fixture] Late after party | 21.2 | 23 min (haversine) | no_registration_evidence | p-fdr-eli |
| 2026-10-29 | 10:00-10:45 | [Fixture] Copilot extensibility deep dive | 56.7 | - | registration_link_found | p-pm-fay, p-pm-gus |
| 2026-10-29 | 13:00-14:00 | [Fixture] Investor office hours | 49.4 | 26 min (haversine) | registration_link_found | p-inv-cleo |
| 2026-10-29 | 19:00-21:00 | [Fixture] Stealth founders dinner | 26.2 | 20 min (unknown_default) | no_registration_evidence | - |

After:

| Day | Time | Event | U | Travel from prev | Registration | Targets |
|---|---|---|---|---|---|---|
| 2026-10-28 | 09:00-10:30 | [Fixture] Opening keynote (simulated time) | 52.5 | - | registration_link_found | p-pm-fay |
| 2026-10-28 | 11:00-11:45 | [Fixture] Building agents with MCP | 53.0 | 5 min (same_venue) | registration_link_found | p-fdr-dev |
| 2026-10-28 | 12:30-13:30 | [Fixture] Copilot PM lunch roundtable | 36.1 | 10 min (haversine) | registration_link_found | p-pm-gus |
| 2026-10-28 | 14:00-16:00 | [Fixture] Agent evals workshop | 28.6 | 10 min (haversine) | no_registration_evidence | - |
| 2026-10-28 | 18:00-20:00 | [Fixture] Seed Investors Happy Hour | 64.5 | 10 min (haversine) | registration_link_found | p-inv-ben, p-inv-hana (probable) |
| 2026-10-28 | 21:30-23:30 | [Fixture] Late after party | 21.2 | 23 min (haversine) | no_registration_evidence | p-fdr-eli |
| 2026-10-29 | 09:00-10:15 | [Fixture] Agents x Seed breakfast | 78.2 | - | registration_link_found | p-fdr-dev, p-inv-cleo |
| 2026-10-29 | 13:00-14:00 | [Fixture] Investor office hours | 49.4 | 25 min (haversine) | registration_link_found | p-inv-cleo |
| 2026-10-29 | 19:00-21:00 | [Fixture] Stealth founders dinner | 26.2 | 20 min (unknown_default) | no_registration_evidence | - |

Why it changed:

- I replace '[Fixture] Copilot extensibility deep dive' with '[Fixture] Agents x Seed breakfast'. '[Fixture] Copilot extensibility deep dive': overlaps '[Fixture] Agents x Seed breakfast' incl. 10 min travel; utility 56.7 vs 78.2. '[Fixture] Agents x Seed breakfast': confirmed targets: Dev Fixture (fictional), Cleo Fixture (fictional); goal topics: ai agents, developer tools. Travel unchanged.
- No fixed appointment touched.

### talk-moved-conflict: A talk is moved and creates a conflict

Change: `time_change`; effects: '[Fixture] Building agents with MCP' moved to Wed 14:30-15:15
Changes vs original: 2 (added 1, removed 1, moved 1)

Before:

| Day | Time | Event | U | Travel from prev | Registration | Targets |
|---|---|---|---|---|---|---|
| 2026-10-28 | 09:00-10:30 | [Fixture] Opening keynote (simulated time) | 52.5 | - | registration_link_found | p-pm-fay |
| 2026-10-28 | 11:00-11:45 | [Fixture] Building agents with MCP | 53.0 | 5 min (same_venue) | registration_link_found | p-fdr-dev |
| 2026-10-28 | 12:30-13:30 | [Fixture] Copilot PM lunch roundtable | 36.1 | 10 min (haversine) | registration_link_found | p-pm-gus |
| 2026-10-28 | 14:00-16:00 | [Fixture] Agent evals workshop | 28.6 | 10 min (haversine) | no_registration_evidence | - |
| 2026-10-28 | 18:00-20:00 | [Fixture] Seed Investors Happy Hour | 64.5 | 10 min (haversine) | registration_link_found | p-inv-ben, p-inv-hana (probable) |
| 2026-10-28 | 21:30-23:30 | [Fixture] Late after party | 21.2 | 23 min (haversine) | no_registration_evidence | p-fdr-eli |
| 2026-10-29 | 10:00-10:45 | [Fixture] Copilot extensibility deep dive | 56.7 | - | registration_link_found | p-pm-fay, p-pm-gus |
| 2026-10-29 | 13:00-14:00 | [Fixture] Investor office hours | 49.4 | 26 min (haversine) | registration_link_found | p-inv-cleo |
| 2026-10-29 | 19:00-21:00 | [Fixture] Stealth founders dinner | 26.2 | 20 min (unknown_default) | no_registration_evidence | - |

After:

| Day | Time | Event | U | Travel from prev | Registration | Targets |
|---|---|---|---|---|---|---|
| 2026-10-28 | 09:00-10:30 | [Fixture] Opening keynote (simulated time) | 52.5 | - | registration_link_found | p-pm-fay |
| 2026-10-28 | 11:15-12:00 | [Fixture] Devtools funding panel | 52.0 | 5 min (same_venue) | registration_link_found | p-inv-ava |
| 2026-10-28 | 12:30-13:30 | [Fixture] Copilot PM lunch roundtable | 36.1 | 10 min (haversine) | registration_link_found | p-pm-gus |
| 2026-10-28 | 14:30-15:15 | [Fixture] Building agents with MCP | 53.0 | 10 min (haversine) | registration_link_found | p-fdr-dev |
| 2026-10-28 | 18:00-20:00 | [Fixture] Seed Investors Happy Hour | 64.5 | 10 min (haversine) | registration_link_found | p-inv-ben, p-inv-hana (probable) |
| 2026-10-28 | 21:30-23:30 | [Fixture] Late after party | 21.2 | 23 min (haversine) | no_registration_evidence | p-fdr-eli |
| 2026-10-29 | 10:00-10:45 | [Fixture] Copilot extensibility deep dive | 56.7 | - | registration_link_found | p-pm-fay, p-pm-gus |
| 2026-10-29 | 13:00-14:00 | [Fixture] Investor office hours | 49.4 | 26 min (haversine) | registration_link_found | p-inv-cleo |
| 2026-10-29 | 19:00-21:00 | [Fixture] Stealth founders dinner | 26.2 | 20 min (unknown_default) | no_registration_evidence | - |

Why it changed:

- I replace '[Fixture] Agent evals workshop' with '[Fixture] Devtools funding panel'. '[Fixture] Agent evals workshop': overlaps '[Fixture] Building agents with MCP'; utility 28.6 vs 53.0. '[Fixture] Devtools funding panel': confirmed targets: Ava Fixture (fictional); entry price unknown. Travel saves 5 min.
- '[Fixture] Building agents with MCP' stays in the plan: time changed from Wed 11:00 to Wed 14:30.
- No fixed appointment touched.

## Errors

- none
