# Starting parallel windows on macOS

**Prerequisite:** main at Window 00 commit `19606fe`, CI green. Keep only the integration owner on `main`.

```bash
cd ~/HTest
git switch main
git pull --ff-only origin main
bash scripts/create_worktrees.sh
```

The script creates worktrees `~/HTest-wNN-slug`, all independently based on the same main commit. **Do not run `git clone` again.** Each new Claude Code/Codex terminal should `cd ~/HTest-wNN-slug` and use the corresponding single-file instruction in `docs/prompts/wNN-slug.md`.

**Launch initially:** w01-luma-partiful, w02-eventbrite-aggregators, w03-official, w04-discovery, w08-graph, w12-api, w13-demo. Optional: w05-lodging and w06-flights can do API-schema mock work now and live probes once keys are available. w07-people, w09-planner, w10-antifomo follow on fixture contracts. w11-travel is optional. w15-integration is reserved for validation of combined work.

**Do not run 14 agents simultaneously by default.** Worktrees can all exist, but only open high-priority terminals. Every agent edits only its owned paths. To keep dependencies stable, new third-party packages require a window 00 PR to update `pyproject.toml`/lock rather than an unsanctioned edit.

**Every window:** implement, test, generate source-attributed probe markdown, commit on its branch, push, open PR into main, never force-push or merge without window 00 checking ownership and CI. On receiving merges, other worktrees can rebase or merge main only after checking their own uncommitted changes. All fixtures are explicitly labelled as synthetic.

**Local check:** `make check`. **Graph:** `make up` if Docker available. **Probe:** `make probe-luma` only if a corresponding owned `scripts/probes/luma.py` was written; the probe Makefile target is generic `make probe-<name>`.
