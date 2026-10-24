# Conferge

**Plan a conference trip in minutes and maximize the professional opportunities you get out of it.**

## Problem

A big conference is two days, hundreds of sessions, dozens of side events and thousands of people.
Agendas are organised by time slot, not by what you came for, so the people who matter to you stay invisible.
Most attendees go home with a few business cards and the feeling they were in the wrong room.

## What it does

1. **Opportunity Graph**: one sentence ("meet seed investors, AI agent founders, Copilot PMs") becomes weighted goals, and official sessions plus side events (Luma, Partiful, Eventbrite, conferenceparties) are linked in FalkorDB to people, companies and topics.
2. **Reverse Planning**: starts from the goals to build a day-by-day plan for the days you are in town, with a map of the venues.
3. **Smart Networking**: who to meet and why, ranked against your goals with the explainable FalkorDB path and its sources; "I met this person" is written to the graph and the ranking changes immediately.
4. **Anti-FOMO**: tells you which events to skip (time conflict, travel too long, low score, outside hours) and what you gain by skipping them.
5. **Live Replanning**: when an event sells out, the plan is recomputed and the diff says what was removed, what replaces it and why.
## Tracks

- **FalkorDB**: the graph of record (697 nodes, 2,195 edges), written only through `GraphStore` MERGE methods and queried for the goal to person explanation paths, conflicts, replanning impact and meeting memory.
- **Bright Data**: SERP discovery, Web Unlocker and the Google Flights, Booking and LinkedIn datasets are implemented behind one client (`conferge/core/brightdata.py`); without an API key they report `missing_credentials` rather than inventing data.
- **Qodo**: planned as the PR review assistant for the workstream PRs; as of submission no Qodo review has run on this repository.

## Measured numbers

Demo case: GitHub Universe 2026, Fort Mason Center, San Francisco, October 28 and 29. Traveller from New York, in town October 27 to 30.

| Measure | Value |
|---|---|
| Live collection, 2026-10-24, public endpoints, no API key | 161 official sessions, 183 speakers, 122 companies, 194 Luma events, 19 Eventbrite events, 11 Partiful events, 7 aggregator parties |
| Demo dataset (snapshot of that collection, deduplicated) | 207 events, 183 people |
| FalkorDB graph | 697 nodes, 2,195 edges (49 HOSTS edges from event organizers), loaded in about 1 s |
| API response times on the demo graph | goal 61 ms, events 8 ms, people 2 ms, graph path 11 ms, plan 8 ms, simulate-change 26 ms, meeting 17 ms, anti-FOMO agent about 1.1 s |
| Tests | 926 passing (`make check`) |

## Links

- Repository: https://github.com/spicyx9/HTest
- Backup video: `docs/submission/demo-backup.mp4` (and `.webm`)
- Slides: `docs/submission/slides.html` (arrow keys to navigate)

## Team

- Axel Carron
- Ilan Sainte Agathe

## Honesty: live vs fixture today

- **Live and working without keys**: official GitHub Universe catalog (RainFocus), Luma, Partiful, Eventbrite, conference-party aggregators, ground travel (BART fares, OSRM routes) and the FalkorDB graph itself.
- **Implemented, waiting for a Bright Data key**: SERP discovery, flights, hotels, LinkedIn enrichment. Today they return `missing_credentials` and the demo shows labelled fixtures for flights and stays.
- **The demo runs on a snapshot** of the live public collection captured on 2026-10-24, labelled `fixture` in every API response and in the UI badge, so it works offline on stage.
- **Simulations are labelled**: the sold-out change in the demo is a simulation, never presented as an observed update.
- **No LLM in the loop yet**: goal parsing and ranking are deterministic; no price, attendance or guest list is ever invented. A public speaker is never presented as a confirmed side-event attendee.
