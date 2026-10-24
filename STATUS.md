# Conferge STATUS — window 00

Last verified: 2026-10-23 PT; GitHub base SHA `7cc2aa5df5d7da3db4c464683ba89f5b4162c1b2`.

## Foundation
- `conferge/core` installed on `main`.
- CI: green as observed before this documentation update; recheck CI on the new head.
- Knowledge: present in `docs/knowledge/` (research only).
- Canonical workstream prompts: `docs/prompts/wNN-<slug>.md`.
- Obsolete prompts: `docs/prompts/wNN.md` and `docs/prompts/_common.md` refer to `backend/app` and are NOT to be run.

## Workstreams
| Window | Branch | Status | PR | CI | Note |
| --- | --- | --- | --- | --- | --- |
| 01 | w01-luma-partiful | queued | — | — | Codex |
| 02 | w02-eventbrite-aggregators | queued | — | — | Codex |
| 03 | w03-official | queued | — | — | Codex |
| 04 | w04-discovery | queued | — | — | Codex, possible fixture |
| 05 | w05-lodging | queued | — | — | needs live credentials to verify |
| 06 | w06-flights | queued | — | — | needs live credentials to verify |
| 07 | w07-people | queued | — | — | Claude, source evidence required |
| 08 | w08-graph | queued | — | — | Claude |
| 09 | w09-planner | queued | — | — | Claude |
| 10 | w10-antifomo | queued | — | — | Claude |
| 11 | w11-travel | queued | — | — | optional |
| 12 | w12-api | queued | — | — | Codex |
| 13 | w13-demo | queued | — | — | Codex |
| 15 | w15-integration | queued | — | — | Claude |

## Next actions
- On Mac: `cd ~/HTest && git pull --ff-only origin main && make check && bash scripts/create_worktrees.sh`.
- Launch Wave 1 in six **independent** worktrees; do not recursively spawn six more agents per worktree.
- Verify PRs before merge, record real progress here.
