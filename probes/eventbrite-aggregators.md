# Probe: eventbrite-aggregators (window 02)

- Run at: 2026-10-24T06:37:39.723413+00:00
- Command: `make probe-eventbrite-aggregators`
- Anchor: GitHub Universe 2026 (`github-universe-2026`), San Francisco, window 2026-10-27..2026-10-30
- Every row below is `live` unless explicitly labelled FIXTURE.

## Run reports

| Source | Target | Mode | Status | Termination | Raw | Unique | Pages | Declared |
|---|---|---|---|---|---|---|---|---|
| eventbrite | SF 2026-10-27..2026-10-30, all events | live | ok | exhausted | 712 | 676 | 15 | 734 |
| eventbrite | SF 2026-10-27..2026-10-30, q=AI | live | ok | exhausted | 727 | 15 | 15 | 750 |
| conferenceparties/github26 | GitHub Universe 2026 (anchor) | live | ok | exhausted | 7 | 7 | 1 | null |
| conferenceparties/reinvent2026 | AWS re:Invent 2026 (parser breadth) | live | ok | exhausted | 95 | 95 | 1 | null |

## Incomplete-window reasons, warnings and errors

- `eventbrite all` warning: declared_count_mismatch:2026-10-27..2026-10-30 declared 734, retrieved 676
- `eventbrite q=AI` warning: declared_count_mismatch:2026-10-27..2026-10-30 declared 750, retrieved 715
- `eventbrite q=AI` warning: keyword_filter_client_side:15 of 715 match ['AI'] (API ignores q)

## Sample normalized events

### conferenceparties.com/github26 (GitHub Universe side events, relation=candidate)

| Title | Start | Venue | Hosts | RSVP | Mode |
|---|---|---|---|---|---|
| Ship It Afterparty | 2026-10-28T17:00:00-07:00 | Left Door | Amplitude | https://amplitude.com/2026-10-github-universe#afterparty | live |
| NeuBird & FluidCloud Happy Hour | 2026-10-28T17:30:00-07:00 | null | NeuBird, FluidCloud | https://na2.hubs.ly/H08xscR0 | live |
| AI Engineering Happy Hour | 2026-10-28T17:30:00-07:00 | Radhaus | Faros | https://pages.faros.ai/connect-with-faros-at-github-universe | live |
| AI in Motion: Charting the Next Frontier | 2026-10-28T17:30:00-07:00 | Culinary Artistas | Slalom, Moderne, Microsoft | https://go.slalom.com/GitHub-Universe-Happy-Hour | live |
| Recovery Hour with Rubrik | 2026-10-28T17:30:00-07:00 | Barrio Restaurant | Rubrik | https://rubrik.registration.goldcast.io/events/e44f07c0-8a90-4556-bd73-9a61845fd1cf | live |
| DevOps on Draft: A Universe Git-Together | 2026-10-28T18:00:00-07:00 | San Francisco Brewing Co | Cloudsmith, Chainguard, Eficode, Octopus Deploy, Tailscale | https://luma.com/git-together | live |
| Xebia’s Broad Street Oyster Bash | 2026-10-28T18:00:00-07:00 | Broad Street Oyster Co. | Xebia | https://events.xebia.com/microsoft/github-universe-broad-street-oyster-bash2026 | live |

### Eventbrite SF, q=AI

| Title | Start | Venue | Organizer | URL | Mode |
|---|---|---|---|---|---|
| AI & Security: Securing the Age of Autonomous AI | 2026-10-28T18:00:00-07:00 | Orrick | AILBA | https://www.eventbrite.com/e/ai-security-securing-the-age-of-autonomous-ai-tickets-2003316175609 | live |
| AI Careers Beyond Coding: AI Consultant, AI Marketer, and AI Builder | 2026-10-28T18:00:00+08:00 | Kingston International College | Kingston International College | https://www.eventbrite.sg/e/ai-careers-beyond-coding-ai-consultant-ai-marketer-and-ai-builder-tickets-2002485891206 | live |
| THE FUTURE OF AI IN SPORTS, GAMES, ENTERTAINMENT & CREATOR ECONOMY | 2026-10-27T14:00:00-07:00 | Fairmont San Francisco | Silicon Valley AI Roadshow | https://www.eventbrite.com/e/the-future-of-ai-in-sports-games-entertainment-creator-economy-tickets-2000775243613 | live |
| AI Tech & Startup Night — San Francisco | 2026-10-28T18:00:00-07:00 | The Liberties | Nomad Global Hub | https://www.eventbrite.com/e/ai-tech-startup-night-san-francisco-tickets-2003175369454 | live |
| AI Startup Pitch & Investor Networking I San Francisco | 2026-10-28T18:00:00-07:00 | Obrien's Irish Pub | Astra Tech Hub, LLC | https://www.eventbrite.com/e/ai-startup-pitch-investor-networking-i-san-francisco-tickets-2003686507281 | live |

Normalization errors: 0

## Eventbrite request actually sent

1. `GET https://www.eventbrite.com/d/ca--san-francisco/events/` (browser User-Agent) sets cookie `csrftoken`; `placeId` read from `window.__SERVER_DATA__`.
2. `POST https://www.eventbrite.com/api/v3/destination/search/` with header `X-CSRFToken` and body:

```json
{
 "event_search": {
  "places": [
   "85922583"
  ],
  "page": 1,
  "page_size": 50,
  "online_events_only": false,
  "date_range": {
   "from": "2026-10-27",
   "to": "2026-10-30"
  },
  "q": "AI"
 },
 "expand.destination_event": [
  "primary_venue",
  "ticket_availability",
  "event_sales_status",
  "primary_organizer"
 ]
}
```

`"dates": "custom"` (older clients) is rejected with ARGUMENTS_ERROR; `date_range` alone is accepted. page_count stops at 19 (950 rows): ranges whose declared total exceeds 900 are split by date; a single day above the cap is reported `page_cap`.

Fixture rebuilt from this live run: `fixtures/eventbrite-aggregators.json`.
