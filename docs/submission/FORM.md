# Patch the Conference: submission form

Copy each field as is. Numbers filled from `STATUS.md` (measured on dfca2bf at 15:33 PDT).

## Project name

Conferge

## One-line tagline

Tell it why you're going to a conference; it tells you who to meet, where, and why.

## Description

Big conferences bury the people who matter to you under hundreds of sessions and side events. Conferge starts from your goal, not the agenda: one sentence such as "meet seed investors, AI agent founders, Copilot PMs" becomes weighted priorities, then who to meet and why, a day-by-day plan, what to skip, and a new plan when an event sells out.

Bright Data is at the core of the data. Its datasets (Booking, Airbnb, LinkedIn, Crunchbase, Google Maps), Web Unlocker (Google Flights) and SERP API collected what a plain request cannot reach: 21 stays, 34 flight itineraries, 17 LinkedIn profiles. Every record keeps its source URL and collection time, and the demo replays that timestamped collection.

FalkorDB is at the core of the reasoning. 194 events with their speakers, companies and topics form a graph of 690 nodes and 2184 edges. FalkorDB ranks the connections, returns the goal-to-person path behind each one as evidence, and remembers who you met. A rule-based planner builds the 25-item itinerary from them. No LLM decides a price, a ranking or an attendance: FalkorDB ranks, Python plans. The optional semantic search uses OpenAI embeddings on FalkorDB's vector index and labels its summary as generated.

## Tracks

- Bright Data
- FalkorDB

## Tech stack

Python, FastAPI, Pydantic, FalkorDB 6.0.3 (falkordb-py, Cypher), Bright Data (Datasets, Web Unlocker, SERP API), httpx, HTML/CSS/vanilla JavaScript with Cytoscape.js, Docker Compose, uv, pytest (1470 tests in `make check`).

## Repository URL

https://github.com/spicyx9/PatchConferenceHack

## How to run

```
make up && make install   # FalkorDB in Docker, Python dependencies with uv
make demo                 # replays the dated Bright Data cache; no key needed, no call at startup
open http://127.0.0.1:8000
```

## Team members

- Axel Carron (GitHub: aaxxeell09)
- Ilan Sainte-Agathe (GitHub: spicyx9)
- Mannan Shukla (GitHub: mannanshukla)

## What is real vs simulated

- Real, collected on 2026-10-24: events and speakers from public sources (official catalog, Luma, Partiful, Eventbrite, conferenceparties), labelled fixture; stays, flights, LinkedIn and Crunchbase through Bright Data, replayed from the timestamped cache and labelled cached.
- Real, computed on stage: the ranking, the evidence paths and the meeting memory come from FalkorDB; nothing is fetched while you watch.
- Simulated: the sold-out event (the replan is real, the source status is not); the traveller persona is a fixture; prices are observed quotes for 2 adults from a past collection, not guaranteed availability, and the return flight segment was not fully collected.
