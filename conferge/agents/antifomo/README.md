# Window 10: anti-FOMO and live replanning

Owned paths: `conferge/agents/antifomo/`, `conferge/agents/replanner/`, `tests/antifomo/`,
`fixtures/antifomo.json`, `scripts/probes/antifomo.py`, `probes/antifomo.md`.

## API

```python
from conferge.agents.antifomo import build_candidates, optimize, explain, verdicts, Constraints
cands = build_candidates(events, goals, people, opportunities)   # utility 0..100 + breakdown
plan = optimize(cands, Constraints(max_per_day=6, blocked=[...]), original=None)
explain(plan)                                                    # KEEP / SKIP lines
verdicts(cands, people)                                          # one Verdict per conflict

from conferge.agents.replanner import Change, PlanningState, apply_change, replan, diff
from conferge.agents.replanner import list_scenarios, run_scenario   # for window 12
```

`run(ctx)` in each package is the `Agent.run` adaptor (`AntiFomoAgent`, `ReplannerAgent`).
Planning constraints are read from `ctx.constraints` (keys of `Constraints`); the replanner also
reads `scenario_id`, `change` and `original_plan` there.

## Decisions

- No PuLP / OR-Tools: adding a dependency means editing `pyproject.toml` (window 0). The optimizer
  is an exact per-day longest-path DP over start-sorted events (`a` may precede `b` only if
  `a.end + travel(a, b) <= b.start`), capped at `max_per_day`. Days are independent because
  travel never spans days. Budget is a repair loop (drop the lowest utility per dollar, re-solve).
- Pathfinder and ConferenceScheduler were used as ideas only (optimize/explain split,
  `original_schedule` minimal change); no code copied, so no licence header needed.
- Minimal change: with `original`, kept items earn and new items pay `change_penalty` (default
  8 utility points). A swap therefore needs a gain over 16 points.
- Presence: confirmed only via `speaker_ids` / `organizer_ids` of that event (or an explicit
  `person_target_available` change); probable only via `public_attendee_listing` and
  `event_ids`. A public speaker elsewhere is not presence.
- Availability is never claimed: items carry `registration_link_found` or
  `no_registration_evidence` (with a warning). Sold out, cancelled and postponed are excluded.
  Events with unknown start or end are rejected (`time_unknown`), never given a guessed slot.
- Travel: haversine at 18 km/h door to door plus 8 min overhead; same venue 5 min; unknown
  coordinates 20 min, flagged `unknown_default`.
- Verdict text is a deterministic template. No OpenAI key tonight; an LLM may rephrase the text
  later but never decides `chosen`.
- Conflicts are computed locally instead of through `conferge.graph.queries.conflicts` so the
  agents run without FalkorDB; the rule is the same, plus the travel buffer.
- Graph writes on replanning go through `GraphStore.merge_node/merge_edge` only. Meetings and
  contacts met are `Meeting` nodes `INVOLVES` a `Person` because `User`, `MET` and `SKIPPED`
  are not in the store allowlist.
