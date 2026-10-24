# Conferge STATUS — window 00

Last verified: 2026-10-23 PT; foundation and post-schema-update CI green. Check current HEAD after pulling.

## Foundation
- `conferge/core` installed on `main`.
- CI: green as observed before this documentation update; recheck CI on the new head.
- Knowledge: present in `docs/knowledge/` (research only).
- Canonical workstream prompts: `docs/prompts/wNN-<slug>.md`.
- Detailed technical specs: `docs/prompts/wNN.md` contain useful endpoints and test details; they **supplement** `wNN-<slug>.md` under the path-mapping/precedence rules in `docs/prompts/README.md`. `_common.md` is a corrected optional preamble. Neither overrides canonical `conferge/` paths.
- Core v0.2 fields are optional and backwards compatible. No window may modify `core/` without the integrator.

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
- Launch Wave 1 in six **independent** worktrees; at most six active agents TOTAL including nested subagents. Claude Code delegation is not automatically Codex CLI. Confirm actual process and branch before counting any window as running.
- Verify PRs before merge, record real progress here.
