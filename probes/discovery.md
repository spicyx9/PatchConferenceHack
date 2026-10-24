# Probe: discovery (window 04)

- collected_at: 2026-10-24T07:32:58.410398+00:00
- anchor: GitHub Universe 2026, Fort Mason Center, San Francisco, 2026-10-28..29
- rule: a SERP hit is a candidate URL, never a confirmed event; Events come only from fetched detail pages and are linked at most as `candidate`.

## Query plan (36 queries)

| family | query | reason |
|---|---|---|
| conference | `"GitHub Universe" San Francisco afterparty` | conference name + 'afterparty' |
| conference | `"GitHub Universe" San Francisco meetup` | conference name + 'meetup' |
| conference | `"GitHub Universe" San Francisco hackathon` | conference name + 'hackathon' |
| conference | `"GitHub Universe" San Francisco happy hour` | conference name + 'happy hour' |
| conference | `"GitHub Universe" San Francisco side event` | conference name + 'side event' |
| conference | `"GitHub Universe" October 2026 party` | conference name + month + party |
| conference | `Universe developer event San Francisco October 2026` | conference alias 'Universe' |
| host | `Amplitude San Francisco October 2026 party` | sponsor/host 'Amplitude' party |
| host | `Amplitude San Francisco October 2026 workshop OR meetup` | sponsor/host 'Amplitude' workshop or meetup |
| host | `Faros San Francisco October 2026 party` | sponsor/host 'Faros' party |
| host | `Faros San Francisco October 2026 workshop OR meetup` | sponsor/host 'Faros' workshop or meetup |
| host | `Rubrik San Francisco October 2026 party` | sponsor/host 'Rubrik' party |
| host | `Rubrik San Francisco October 2026 workshop OR meetup` | sponsor/host 'Rubrik' workshop or meetup |
| host | `Xebia San Francisco October 2026 party` | sponsor/host 'Xebia' party |
| host | `Xebia San Francisco October 2026 workshop OR meetup` | sponsor/host 'Xebia' workshop or meetup |
| host | `Cloudsmith San Francisco October 2026 party` | sponsor/host 'Cloudsmith' party |
| host | `Cloudsmith San Francisco October 2026 workshop OR meetup` | sponsor/host 'Cloudsmith' workshop or meetup |
| host | `Chainguard San Francisco October 2026 party` | sponsor/host 'Chainguard' party |
| host | `Chainguard San Francisco October 2026 workshop OR meetup` | sponsor/host 'Chainguard' workshop or meetup |
| venue_date | `San Francisco tech event October 27 2026` | city + date 2026-10-27 without conference keywords |
| venue_date | `San Francisco tech event October 28 2026` | city + date 2026-10-28 without conference keywords |
| venue_date | `San Francisco tech event October 29 2026` | city + date 2026-10-29 without conference keywords |
| venue_date | `San Francisco tech event October 30 2026` | city + date 2026-10-30 without conference keywords |
| venue_date | `"Fort Mason Center" San Francisco event October 2026` | venue + month without conference keywords |
| goal | `"AI agents" San Francisco October 2026 event` | goal topic 'AI agents' |
| goal | `"developer tools" San Francisco October 2026 event` | goal topic 'developer tools' |
| goal | `MCP San Francisco October 2026 event` | goal topic 'MCP' |
| platform | `site:luma.com San Francisco October 27 2026` | site:luma.com for 2026-10-27 |
| platform | `site:luma.com San Francisco October 28 2026` | site:luma.com for 2026-10-28 |
| platform | `site:luma.com San Francisco October 29 2026` | site:luma.com for 2026-10-29 |
| platform | `site:luma.com San Francisco October 30 2026` | site:luma.com for 2026-10-30 |
| platform | `site:partiful.com San Francisco October 2026 developer OR AI` | site:partiful.com for the conference month |
| platform | `site:eventbrite.com San Francisco October 2026 developer OR AI` | site:eventbrite.com for the conference month |
| platform | `site:meetup.com San Francisco October 2026 developer OR AI` | site:meetup.com for the conference month |
| platform | `site:facebook.com/events San Francisco October 2026 developer OR AI` | site:facebook.com/events for the conference month |
| platform | `site:linkedin.com/events San Francisco October 2026 developer OR AI` | site:linkedin.com/events for the conference month |

## 1. Live SERP (Bright Data)

- `brightdata_serp` status=**failed** termination=`error` mode=`live` fetched=0 unique=0 pages=0
- error: Bright Data key missing; set BRIGHTDATA_API_KEY

## 2. Candidates: FIXTURE (live SERP failed)

Explicit fixture `fixtures/discovery.json`: synthetic SERP replay built from real URLs captured live by w01/w02. Query to URL pairing is constructed, not observed.

- `brightdata_serp` status=**ok** termination=`not_applicable` mode=`fixture` fetched=14 unique=13 pages=36

| conf. | platform | adapter | kind | canonical URL | first query | mode |
|---|---|---|---|---|---|---|
| 0.75 | luma | luma | event_or_calendar | https://luma.com/git-together | `"GitHub Universe" San Francisco afterparty` | fixture |
| 0.5 | eventbrite | eventbrite | event_page | https://eventbrite.com/e/ai-startup-pitch-investor-networking-i-san-francisco-tickets-2003686507281 | `site:eventbrite.com San Francisco October 2026 developer OR AI` | fixture |
| 0.4 | aggregator | aggregators | listing | https://conferenceparties.com/github26 | `"GitHub Universe" San Francisco afterparty` | fixture |
| 0.4 | luma | luma | event_or_calendar | https://luma.com/0m8oub77 | `San Francisco tech event October 29 2026` | fixture |
| 0.4 | luma | luma | event_or_calendar | https://luma.com/69r7rj77 | `site:luma.com San Francisco October 28 2026` | fixture |
| 0.4 | luma | luma | event_or_calendar | https://luma.com/xueo91fw | `San Francisco tech event October 29 2026` | fixture |
| 0.4 | luma | luma | event_or_calendar | https://luma.com/you-halloween | `site:luma.com San Francisco October 28 2026` | fixture |
| 0.3 | generic | jsonld | other | https://amplitude.com/2026-10-github-universe | `"GitHub Universe" San Francisco afterparty` | fixture |
| 0.3 | generic | jsonld | other | https://events.xebia.com/microsoft/github-universe-broad-street-oyster-bash2026 | `Xebia San Francisco October 2026 party` | fixture |
| 0.3 | generic | jsonld | other | https://go.slalom.com/GitHub-Universe-Happy-Hour | `"GitHub Universe" San Francisco happy hour` | fixture |
| 0.3 | generic | jsonld | other | https://pages.faros.ai/connect-with-faros-at-github-universe | `"GitHub Universe" San Francisco happy hour` | fixture |
| 0.3 | generic | jsonld | other | https://rubrik.registration.goldcast.io/events/e44f07c0-8a90-4556-bd73-9a61845fd1cf | `Rubrik San Francisco October 2026 party` | fixture |
| 0.1 | luma | none | listing | https://luma.com/discover | `site:luma.com San Francisco October 28 2026` | fixture |

## 3. Detail verification (LIVE public pages via router)

- envelope: mode=`mixed` status=**ok** events=6
- `brightdata_serp` status=**ok** termination=`not_applicable` mode=`fixture` fetched=14 unique=13 pages=36
- `discovery_details` status=**ok** termination=`not_applicable` mode=`live` fetched=11 unique=6 pages=11

| candidate URL | adapter | outcome | detail provider | note |
|---|---|---|---|---|
| https://luma.com/git-together | luma | **verified** | luma | null |
| https://eventbrite.com/e/ai-startup-pitch-investor-networking-i-san-francisco-tickets-2003686507281 | eventbrite | **verified** | eventbrite | null |
| https://conferenceparties.com/github26 | aggregators | **skipped** | null | no detail adapter in window 04; left to its owning window |
| https://luma.com/0m8oub77 | luma | **verified** | luma | null |
| https://luma.com/69r7rj77 | luma | **verified** | luma | null |
| https://luma.com/xueo91fw | luma | **verified** | luma | null |
| https://luma.com/you-halloween | luma | **verified** | luma | null |
| https://amplitude.com/2026-10-github-universe | jsonld | **unverified** | web_jsonld | detail page describes the anchor conference itself, not a side event |
| https://events.xebia.com/microsoft/github-universe-broad-street-oyster-bash2026 | jsonld | **unverified** | null | no schema.org Event JSON-LD on page; LLM extraction unavailable (no key), candidate kept unverified |
| https://go.slalom.com/GitHub-Universe-Happy-Hour | jsonld | **unverified** | null | no schema.org Event JSON-LD on page; LLM extraction unavailable (no key), candidate kept unverified |
| https://pages.faros.ai/connect-with-faros-at-github-universe | jsonld | **unverified** | null | no schema.org Event JSON-LD on page; LLM extraction unavailable (no key), candidate kept unverified |
| https://rubrik.registration.goldcast.io/events/e44f07c0-8a90-4556-bd73-9a61845fd1cf | jsonld | **unverified** | null | no schema.org Event JSON-LD on page; LLM extraction unavailable (no key), candidate kept unverified |
| https://luma.com/discover | none | **skipped** | null | no detail adapter in window 04; left to its owning window |

### Events (normalized from detail pages)

| title | start | venue | relation | score | mode | source |
|---|---|---|---|---|---|---|
| DevOps on Draft: A Universe Git-Together | 2026-10-28T18:00:00-07:00 | San Francisco Brewing Co. | candidate | 0.85 | live | https://luma.com/git-together |
| AI Startup Pitch & Investor Networking I San Francisco | 2026-10-28T18:00:00-07:00 | Obrien's Irish Pub | unknown | 0.2 | live | https://eventbrite.com/e/ai-startup-pitch-investor-networking-i-san-francisco-tickets-2003686507281 |
| Entire Espresso with Gergely Orosz and Thomas Dohmke | 2026-10-29T09:00:00-07:00 | null | unknown | 0.35 | live | https://luma.com/0m8oub77 |
| Agentic Infrastructure Stack Summit | 2026-10-28T09:00:00-07:00 | Terra Gallery & Event Venue | unknown | 0.45 | live | https://luma.com/69r7rj77 |
| Agent Builders Breakfast - Founders & Builders in SOMA, SF | 2026-10-29T08:00:00-07:00 | null | unknown | 0.45 | live | https://luma.com/xueo91fw |
| Hack With YOU @AWS Builder Loft - Halloween Edition | 2026-10-28T09:00:00-07:00 | AWS Builder Loft | candidate | 0.65 | live | https://luma.com/you-halloween |

### Dedup groups

- luma:evt-318Z1ieJkGcCmcr: unique (1.0) 
- evt:eventbrite:2003686507281: unique (1.0) 
- luma:evt-ZC2PPpdaK1O3l3v: unique (1.0) 
- luma:evt-PIhNiH8vJ8axnTE: unique (1.0) 
- luma:evt-pQLZuaisAei0vHC: unique (1.0) 
- luma:evt-GuR42PVSB03OQ7N: unique (1.0) 

## 4. Facebook Events (Bright Data dataset gd_m14sd0to1jz48ppm51)

- `facebook_events` status=**failed** termination=`error` mode=`live` fetched=0 unique=0 pages=0
- error: FacebookEventsError: Bright Data key missing; set BRIGHTDATA_API_KEY

No fixture substituted for Facebook: a failed run stays failed.

