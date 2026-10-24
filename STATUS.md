# STATUS (auto, 2026-10-24T06:25:37Z) active=6 wave1_merged=0/6 wave2_merged=0/4

## Morning summary
- Wave 1: 0/6 merged; wave 2: 0/4 merged.
- w15 integration: pending.
- Pending live credentials and probes: w05 lodging, w06 flights, w07 people and w04 Bright Data live.
- Morning checklist: verify GitHub CI and PRs, inspect fixture labels, configure Bright Data and OpenAI keys locally, test real FalkorDB traversal, rehearse the 3-minute scenario.

| window | slug | tool | state | last commit | PR | CI | note |
|---|---|---|---|---|---|---|---|
| w01 | luma-partiful | claude | running | - | - | - | - |
| w02 | eventbrite-aggregators | claude | running | - | - | - | - |
| w03 | official | claude | running | - | - | - | - |
| w04 | discovery | claude | queued | - | - | - | - |
| w05 | lodging | codex | queued | - | - | - | - |
| w06 | flights | codex | queued | - | - | - | - |
| w07 | people | claude | queued | - | - | - | - |
| w08 | graph | claude | running | - | - | - | - |
| w09 | planner | claude | queued | - | - | - | - |
| w10 | antifomo | claude | queued | - | - | - | - |
| w11 | travel | claude | queued | - | - | - | - |
| w12 | api | claude | running | - | - | - | - |
| w13 | demo | claude | running | - | - | - | - |
| w15 | integration | claude | queued | - | - | - | - |

Logs: logs/wNN.log, logs/watch.log. Relaunch a worker: bash scripts/ops/launch_worker.sh NN slug. Launch wave 3 (needs keys in .env of each worktree): bash scripts/ops/launch_wave.sh 3
