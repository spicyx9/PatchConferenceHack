# Conferge

**Plan a conference trip in minutes and maximize the professional opportunities you get out of it.**

## Problem

A big conference is two days, hundreds of sessions, dozens of side events and thousands of people.
Agendas are organised by time slot, not by what you came for, so the people who matter to you stay invisible.
Most attendees go home with a few business cards and the feeling they were in the wrong room.

## What it does

1. **Goal first**: one sentence ("meet seed investors, AI agent founders, Copilot PMs") becomes weighted goals. Rule based, 25 of 25 sentences of the coverage test recognised in French and English.
2. **Event discovery**: official sessions plus side events from Luma, Partiful, Eventbrite and party aggregators, linked to the conference.
3. **Who to meet, and why**: people ranked against your goals, each with the FalkorDB path from goal to person and its sources.
4. **Reverse planning**: a day-by-day plan for the days you are in town, with a map of the venues (straight lines in visit order, labelled as such).
5. **Anti-FOMO and live replanning**: which events to skip (time conflict, travel too long, low score) and what you gain by skipping them; when an event sells out, the plan is recomputed and the diff explains what was removed, what replaces it and why.
6. **Memory and follow-up draft**: "I met this person" is written to the graph and the ranking changes immediately; a follow-up draft built from that graph path and your note is then proposed for validation, never sent.
7. **ROI panel**: four figures for the trip (meetings recorded, qualified contacts, opportunities scored 30 or more, budget against collected flight and lodging prices; spend stays unknown until prices are collected).

## Tracks

- **FalkorDB**: the graph of record (697 nodes, 2,195 edges), written only through `GraphStore` MERGE methods and queried for the goal to person explanation paths, conflicts, replanning impact and meeting memory.
- **Bright Data**: SERP discovery, Web Unlocker and the Google Flights, Booking and LinkedIn datasets are implemented behind one client (`conferge/core/brightdata.py`); without an API key they report `missing_credentials` rather than inventing data.
- **Qodo**: installed on the repository as the GitHub app `qodo-code-review[bot]`; it posted a PR summary on pull requests 6 and 7 and its full review on pull request 6 failed on Qodo's side. No Qodo finding has been acted on yet.

## Measured numbers

Demo case: GitHub Universe 2026, Fort Mason Center, San Francisco, October 28 and 29. Traveller from New York, in town October 27 to 30.

| Measure | Value |
|---|---|
| Live collection, 2026-10-24, public endpoints, no API key | 161 official sessions, 183 speakers, 122 companies, 194 Luma events, 19 Eventbrite events, 11 Partiful events, 7 aggregator parties |
| Demo dataset (snapshot of that collection, deduplicated) | 207 events, 183 people, 122 companies |
| FalkorDB graph | 697 nodes, 2,195 edges (49 HOSTS edges from event organizers), loaded in about 1 s |
| API response times on the demo graph | goal 61 ms, events 8 ms, people 2 ms, graph path 11 ms, plan 8 ms, simulate-change 26 ms, meeting 17 ms, anti-FOMO agent about 1.1 s |
| Tests | 1,062 passed, 22 skipped (`uv run pytest -q`, branch `w21-risk5-submission` on main 933cc72, 2026-10-24; main alone: 1,057 passed) |

## Links

- Repository: https://github.com/spicyx9/PatchConferenceHack
- Backup video: `docs/submission/demo-backup.mp4` (and `.webm`)
- Slides: `docs/submission/slides.html` (7 slides, arrow keys to navigate)
- Pitch script: `docs/submission/PITCH.md` (3 minutes, timed, with the wifi-down variant)
- Stage checklist: `docs/submission/CHECKLIST.md`

## Team

- Axel Carron
- Ilan Sainte Agathe

## Honesty: live vs fixture today

Checked against the code on main (2026-10-24) and the wiring audit of 2026-10-24 (read-only audit, not yet merged).

- **Live and working without keys**: official GitHub Universe catalog (RainFocus), Luma, Partiful, Eventbrite and conference-party aggregators (`run_demo.py --mode live`), and the FalkorDB graph itself.
- **The demo runs on a snapshot** of that public collection captured on 2026-10-24: 207 events, 183 people, 122 companies after deduplication, labelled `fixture` in every API response and in the UI badge, so it works offline on stage.
- **Implemented, waiting for a Bright Data key**: SERP discovery, flights, hotels, LinkedIn enrichment. Without `BRIGHTDATA_API_KEY` the client reports "Bright Data key missing", `GET /brightdata` answers `data_source: unknown` with a warning, lodging providers report `missing_credentials`, and flights and stays fall back to fixtures labelled as such.
- **The traveller profile is a fixture even in live mode**: New York, October 27 to 30, budget $2,500 come from `fixtures/api.json`; the budget block carries `source_mode: fixture` in `GET /travel` and a FIXTURE badge in the UI.
- **Live people are the speakers of the official catalog only**: no GitHub or LinkedIn enrichment runs in the demo path.
- **Ground travel is not in the demo**: BART, OSRM and walking connectors exist with a probe (`make probe-travel`) but the demo API does not call them; the map draws straight lines in visit order and says so.
- **A travel proposal books nothing**: the button is "Note" and the API returns `books: false`.
- **Simulations are labelled**: the sold-out change is a simulation; every later response carries a warning until Reset.
- **No LLM in the loop**: goal parsing is rule based (`conferge/agents/planner/goals.py`), the anti-FOMO agent uses templates, ranking is deterministic; no price, attendance or guest list is ever invented. A public speaker is never presented as a confirmed side-event attendee.
