# STATUS (auto, 2026-10-24T06:19:01Z) active=6 wave1_merged=0/6
| window | slug | tool | state | last commit | PR | CI | note |
|---|---|---|---|---|---|---|---|
| w01 | luma-partiful | claude | running | - | - | - | relaunched (attempt 2) |
| w02 | eventbrite-aggregators | claude | running | - | - | - | relaunched (attempt 2) |
| w03 | official | claude | running | - | - | - | relaunched (attempt 2) |
| w04 | discovery | claude | queued | - | - | - | - |
| w05 | lodging | codex | queued | - | - | - | - |
| w06 | flights | codex | queued | - | - | - | - |
| w07 | people | claude | queued | - | - | - | - |
| w08 | graph | claude | running | - | - | - | relaunched (attempt 2) |
| w09 | planner | claude | queued | - | - | - | - |
| w10 | antifomo | claude | queued | - | - | - | - |
| w11 | travel | claude | queued | - | - | - | - |
| w12 | api | claude | running | - | - | - | relaunched (attempt 2) |
| w13 | demo | claude | running | - | - | - | relaunched (attempt 2) |
| w15 | integration | claude | queued | - | - | - | - |

Logs: logs/wNN.log, logs/watch.log. Relaunch a worker: bash scripts/ops/launch_worker.sh NN slug. Launch wave 3 (needs keys in .env of each worktree): bash scripts/ops/launch_wave.sh 3
