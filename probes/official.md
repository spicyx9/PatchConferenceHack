# Probe: official (GitHub Universe 2026)

- Probe run at: 2026-10-24T06:33:16.195150+00:00
- Data mode: **live** (live HTTP calls during this probe)
- Status: **ok**; collected_at: 2026-10-24T06:33:16.126752+00:00
- Source: RainFocus public catalog behind the official attendee portal
  - portal: https://reg.githubuniverse.com/ (workflow `github.universe26.attendee-portal`)
  - sessions page: https://reg.githubuniverse.com/flow/github/universe26/attendee-portal/page/sessioncatalog
  - sponsors page: https://reg.githubuniverse.com/flow/github/universe26/attendee-portal/page/sponsors
  - JSON API: POST https://events.rainfocus.com/api/search (type=session|exhibitor, from=offset)
  - widget id and api profile token are read at runtime from `flow/loadPage?pageUri=<page>&workflowApiToken=<workflow>` (not stored)
- Bright Data: not needed (public JSON endpoint, no blocking observed). Unlocker remains the fallback if the portal starts blocking.

## Run report

| field | value |
|---|---|
| status | ok |
| termination | exhausted |
| source_mode | live |
| pages | 6 |
| fetched_count | 210 |
| unique_count | 210 |
| expected_count (declared by source) | 210 |

Report warnings:

- session: exhausted, 156 items
- exhibitor: exhausted, 54 items

## Normalized output

- Events: 161 (one per published time slot)
- People: 183 (all from official catalog participant lists)
- Companies: 122 (54 sponsors/exhibitors)
- Events with start_at: 161; with speakers: 137; with room: 161

| event_type, conference_relation | count |
|---|---|
| session, official | 123 |
| party, confirmed_side_event | 17 |
| party, official | 9 |
| workshop, official | 5 |
| other, official | 5 |
| meetup, confirmed_side_event | 2 |

| person participation | count |
|---|---|
| confirmed_speaker | 183 |

| sponsor tier | count |
|---|---|
| sponsor_tier:bronze | 24 |
| sponsor_tier:signal | 9 |
| sponsor_tier:silver | 8 |
| sponsor_tier:gold | 8 |
| sponsor_tier:platinum | 5 |

## Sample records

- `official:github-universe-2026:1791496551347001vZmf` A Taste of the Craft - Hosted by Rewind | 2026-10-26 18:30:00-07:00 | Redwood Empire Whiskey | confirmed_side_event
- `official:github-universe-2026:1792686672160001uV6o` Universe Badge Pickup Party! | 2026-10-27 15:00:00-07:00 | Hotel Zephyr @ 250 Beach St | official
- `official:github-universe-2026:1791439808609001QKlO` San Francisco Syntax Meetup | 2026-10-27 17:00:00-07:00 | Barebottle Beer Garden @ 1525 Cortland Ave | confirmed_side_event
- `official:github-universe-2026:1786370222106001jLNQ` Opening Keynote | 2026-10-28 09:00:00-07:00 | Main Stage @ Festival Pavilion | official
- `official:github-universe-2026:1792185348451001YuAA:1792185371345001yiQP` Watch the Keynote from Cowell Theater | 2026-10-28 09:00:00-07:00 | Cowell Theater @ Gateway Pavilion | official
- side event `official:github-universe-2026:1791439808699001Qagl` AI in Motion: New Trajectories Evening Reception | 2026-10-28 17:30:00-07:00 | Culinary Artistas
- side event `official:github-universe-2026:1791496551347001vZmf` A Taste of the Craft - Hosted by Rewind | 2026-10-26 18:30:00-07:00 | Redwood Empire Whiskey
- side event `official:github-universe-2026:1791439808002001Qc4X` Bitrise Connect San Francisco | 2026-10-28 18:00:00-07:00 | Flores San Francisco

## Normalization warnings

- ambiguous track x3
- no published speakers x3

## Completeness notes

- Times: explicit UTC from the catalog, local America/Los_Angeles derived; no time is invented.
- `Social` items are sponsor or partner evening events listed by the organizer: `confirmed_side_event`, distinct from official sessions.
- Speakers are `confirmed_speaker` only for the listed published sessions; this is not attendance evidence for anything else.
- Prices, guest lists and attendance are not published by this source: null.
- Venue coordinates are not published: coordinate_precision=unknown.

## Fixture

fixtures/official.json rewritten from this live run (378395 bytes), labelled source_mode=fixture.
