# Probe: LinkedIn URL discovery by Bright Data SERP

- run at: 2026-10-24T20:43:12.089882+00:00 (292.8 s)
- targets: 17 announced speakers without linkedin_url (max 30)
- SERP: zone serp_api1, POST /request, google.com/search?...&brd_json=1&gl=us, JSON organic only -> data/probes/linkedin_serp_20261024T204311Z.json
- URLs found: **5/17**; not found: 11; failed: 1
- Person.linkedin_url written (brightdata:serp): 5
- dataset batch: POST /datasets/v3/trigger, 3 inputs, snapshot sd_mvmv717h1u6buxciol, status ok, 3 rows
- private or hidden (warning_code): 0
- profiles from data/probes for found URLs: 5
- profiles enriched (name confirmed): **5**; name mismatch: 0; headline from position: 0, from SERP title: 5
- graph: 5 Person, 5 WORKS_AT (5 corroborated); no ATTENDS
- cost returned by the API: none (no cost header in the responses)

## Lookups

| speaker | company | verdict | score | reason |
|---|---|---|---|---|
| Abel Berhane | GitHub | not_found | 0.6 | neither company nor title corroborates |
| Philip Holleran | GitHub | found | 0.9 | tie broken: the person's title is on this hit only |
| Zachary Pollock | Chevron | not_found | 0.3 | name in the SERP title does not match |
| Matt Alvarez | GitHub | not_found | 0.8 | name in the SERP title does not match |
| Martin Woodward | GitHub | found | 0.9 | tie broken: the person's title is on this hit only |
| Ryan Platt | Vanguard | not_found | 0.35 | neither company nor title corroborates |
| Parker Johnston | Insight | found | 0.9 | +0.1 slug contains first and last name |
| Bas Alberts | GitHub | not_found | 0.6 | neither company nor title corroborates |
| Madelyn Tarr | Amplitude | found | 0.9 | +0.1 slug contains first and last name |
| David Slater | GitHub | found | 0.9 | +0.1 slug contains first and last name |
| Jay Parikh | Microsoft | failed | - | SERP answer is not JSON (brd_json=1 expected) |
| Cassidy Williams | GitHub | not_found | 0.5 | neither company nor title corroborates |
| Damian Brady | GitHub | not_found | - | no linkedin.com/in result |
| Benedict Mak | Manulife | not_found | 0.3 | name in the SERP title does not match |
| William Woodruff | OpenAI | not_found | 0.5 | neither company nor title corroborates |
| Tim Mason | Marks and Spencer | not_found | 0.6 | neither company nor title corroborates |
| Michael Beemer | Dynatrace | not_found | - | no linkedin.com/in result |
