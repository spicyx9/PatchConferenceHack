# Conference participant journey audit

2026-10-24. Three agent persona reviews, supported by local fixture navigation, existing screenshots, source inspection and pure goal-parser probes. These are simulated participant reviews, not interviews or usability tests with real participants. The founder review used source/screenshots; the developer and traveler reviews also inspected the local application.

## Product decision

Start with the participant's mission: conference, desired outcome, availability and travel needs. GitHub Universe is the currently supported conference/context, not the identity of the product. The purpose is to make attendance worthwhile; flights and lodging support that purpose.

## Persona findings

| Persona | Desired outcome | Current blocker | Required behavior |
| --- | --- | --- | --- |
| Founder from New York | Meet seed investors within a trip budget | Existing founder mission and 36 agenda entries appear before the participant provides intent | Confirm conference and mission; distinguish proposed agenda from retained choices; explain each relevant person/session |
| Local independent developer | Learn MCP/Copilot through practical workshops | Learning goals fall back to networking defaults; travel assumes flights; out-of-trip events appear in discovery | Support learning before offering it as a goal; optional travel; conference/city/date-scoped discovery |
| International speaker from Paris | Arrive before speaking, carry luggage, stay nearby | Search edits only external links; no matching internal collection; no explicit retained flight/hotel | Criteria → collection → contextual results → explicit option → provider; inherit destination/venue from conference |

Observed parser failure: `I want to learn secure MCP through practical workshops, not meet investors.` becomes an investor goal. A learning-only request produces the founder defaults. These remain open defects; new UI must not claim that learning personalization works.

## Intended flow

1. **Choose your conference.** Show the loaded conference, city, dates and venue. Until discovery/import exists, do not present other conferences as selectable working options.
2. **Define your outcome.** Relevant people, learning topics or business opportunities. Store the actual supported intent; reject or explain unsupported input instead of silently substituting founder defaults.
3. **Set availability and travel needs.** Attendance dates, origin, travelers, budget; local / need travel / already arranged. Avoid irrelevant flight questions for local attendees.
4. **Review a proposed agenda.** A small useful set of sessions/people, clear reasons, keep/replace/remove actions and room for free time. Scope browsing to the active trip by default.
5. **Research travel if needed.** Separate Flights and Stays. Destination derives from the conference; dates and traveler counts remain shared and visible.
6. **During and after attendance.** Record participation and conversations, adjust plans, review follow-ups and outcomes that correspond to the original intent.

## Search contracts required before implementing the next UI

- Flight criteria: origin, destination, departure/return or one-way, adults, cabin. Results: observed total/currency and scope, local departure/arrival times, duration, stops, baggage when known, source time and provider URL. Filters apply to the returned search result set.
- Stay criteria: conference city/venue, dates, guests, rooms, radius and budget. Results: name, total for the exact stay, availability, known fees/taxes, cancellation, rating, coordinates/proximity and provider URL. Use source images only if provided by the schema/source.
- Search results must have their own criteria, request identity and status. Editing criteria must invalidate or clearly separate earlier results. Do not mutate the trip's selected options just by searching.
- Retaining an option requires an explicit user action. A quoted offer is not booked. A budget must not subtract arbitrary first results as if selected.
- Missing credentials, unsupported criteria and provider failures need specific recoverable errors, with an external search using the same criteria as a fallback.

## Existing implementation boundaries

`GET /flights` and `/stays` expose assembled records. The opt-in `/flights?alternatives=true` exposes deduplicated cached alternatives only in a cached session; it does not collect a new search or change the itinerary. Current research links open external providers. No flight/stay selection is persisted.

The services accept structured flight/lodging queries, but this alone does not prove generic collection works. The current Google Flights snapshot provider does not filter all date/occupancy/cabin criteria; Web Unlocker is restricted to the NYC–SFO scenario, one adult/economy. These adapters need validation or correction before exposing a generic Paris search. Never return Universe cache results for unrelated criteria.

## Verification gates for the next increment

- The local learner is never asked for a flight and is not converted into an investor persona.
- A changed conference context updates city, dates, agenda and travel constraints consistently; unsupported conferences remain explicit.
- A flight/stay search returns only results matching its criteria or a clear unsupported/failed/empty state.
- Cached offers retain collection dates and price scope. Missing baggage, tax and booking details remain unknown.
- A selected option is distinguishable from a suggestion and survives the supported session lifecycle.

Design references: [KAYAK search and discovery](https://www.kayak.com/c/help/search/) and [Airbnb search filters](https://www.airbnb.com/help/article/479). Reuse their familiar criteria → results → filtering → provider sequence, connected to conference intent.
