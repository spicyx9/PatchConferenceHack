# Probe: people (window 07)

Run at 2026-10-24T16:34:49.268462+00:00.

## 1. Candidate collection (FIXTURE replay, not live)

- source_mode: **fixture**, status: ok
- inputs: fixtures/official.json (public GitHub Universe 2026 RainFocus catalog), fixtures/luma.json (public Luma event pages, hosts only)
- raw profiles: 215; unique after dedup: 215; ambiguous same-name pairs (not merged): 0
- confirmed speakers: 183; confirmed hosts: 32; catalog-declared LinkedIn URLs: 166 (none guessed)
- guest lists read: 0 (never)

- report rainfocus:github-universe-2026: ok/not_applicable, fixture, fetched=210; FIXTURE: replay of public catalog captured at 2026-10-24T06:33:16.126752+00:00; not a live response
- report luma: ok/not_applicable, fixture, fetched=12; FIXTURE: luma.json; captured 2026-10-24T06:29:34.196299+00:00; not live

## 2. Bright Data SERP name + company -> LinkedIn (live attempt)

- status: **missing_credentials** (run_report status=failed, termination=error)
- source_mode: live; queries: 3; records: 0
- targets: Martin Woodward, Zachary Pollock, Benedict Mak
- error: missing_credentials: BRIGHTDATA_API_KEY / BRIGHTDATA_SERP_ZONE not set

## 3. Public GitHub API (live attempt, no key)

- status: **ok**, source_mode: live
- https://github.com/octocat collected_at 2026-10-24T16:34:49.592293+00:00, 6 non-fork repos
- connectivity check only; no fixture person has a declared GitHub URL, so nothing was applied (no name-based guessing).

## 4. Ranking vs demo goals (deterministic, offline, data is FIXTURE)

- status: ok; source_mode: fixture; scorer: deterministic; considered: 215; shortlisted: 50

| # | person | roles | score | presence | where (from event) |
|---|---|---|---|---|---|
| 1 | Camila Maia | founder | 68.8 | confirmed | How one open source project turned funding into se @ 2026-10-28T10:30:00-07:00 |
| 2 | Dylan Ratcliffe | founder, executive | 61.6 | confirmed | Write-only code: What happens to peer review when  @ 2026-10-29T10:00:00-07:00 |
| 3 | Julia Kasper | pm | 61.6 | confirmed | Your benchmark is lying: What evals actually look  @ 2026-10-28T10:30:00-07:00 |
| 4 | Adam Jacob | founder, executive | 61.6 | confirmed | Write-only code: What happens to peer review when  @ 2026-10-29T10:00:00-07:00 |
| 5 | Andrew Norris | pm | 61.6 | confirmed | Your agents write the fix. Observability supplies  @ 2026-10-29T10:00:00-07:00 |
| 6 | Ron Efroni | founder, executive | 60.0 | confirmed | The O(1) patch: Securing the supply chain against  @ 2026-10-28T13:40:00-07:00 |
| 7 | Mina Tawadrous | pm | 58.4 | confirmed | Prioritization as code: Assumptions by pull reques @ 2026-10-29T13:20:00-07:00 |
| 8 | Jeff An | founder, executive | 58.4 | confirmed | Beyond pass or fail: How agents verify AI-generate @ 2026-10-29T09:00:00-07:00 |
| 9 | Pierre Tempel | pm | 54.4 | confirmed | Agentic security for every developer @ 2026-10-28T14:30:00-07:00 |
| 10 | Tim Rogers | pm | 54.4 | confirmed | Automate the everyday with Copilot Automations @ 2026-10-28T14:05:00-07:00 |

Presence is confirmed only for published speakers and hosts. Investor matches are absent because the public catalog lists no seed investors as speakers; none were invented.
