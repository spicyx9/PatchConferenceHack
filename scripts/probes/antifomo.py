"""Probe for window 10: agenda, anti-FOMO verdicts and replanning scenarios.

Writes ``probes/antifomo.md``. Input data is the labelled synthetic fixture
``fixtures/antifomo.json`` (there is no provider behind the agents). FalkorDB is
probed for reachability; scenario graph writes are attempted only when
``ANTIFOMO_PROBE_GRAPH_WRITE=1`` so fixture nodes never land in the shared graph
by accident.
"""

from __future__ import annotations

import os
import socket
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from conferge.agents.antifomo import build_candidates, explain, optimize, verdicts  # noqa: E402
from conferge.agents.antifomo.fixture import FIXTURE_PATH, load_fixture  # noqa: E402
from conferge.agents.antifomo.models import Plan  # noqa: E402
from conferge.agents.replanner import list_scenarios, run_scenario, state_from_fixture  # noqa: E402

OUT = ROOT / "probes" / "antifomo.md"


def _graph_status() -> tuple[str, object | None]:
    host = os.getenv("FALKORDB_HOST", "127.0.0.1")
    port = int(os.getenv("FALKORDB_PORT", "6379"))
    try:
        with socket.create_connection((host, port), timeout=0.3):
            pass
    except OSError:
        return f"FalkorDB {host}:{port} unreachable; graph writes not attempted", None
    if os.getenv("ANTIFOMO_PROBE_GRAPH_WRITE") != "1":
        return (f"FalkorDB {host}:{port} reachable; writes skipped "
                "(set ANTIFOMO_PROBE_GRAPH_WRITE=1 to record scenario changes)"), None
    try:
        from conferge.core.store import connect_graph

        store = connect_graph()
        store.graph.query("RETURN 1")
        return f"FalkorDB {host}:{port} live; scenario changes written via GraphStore", store
    except Exception as exc:  # noqa: BLE001
        return f"FalkorDB {host}:{port} error {type(exc).__name__}; writes skipped", None


def _plan_table(plan: Plan) -> list[str]:
    rows = ["| Day | Time | Event | U | Travel from prev | Registration | Targets |",
            "|---|---|---|---|---|---|---|"]
    for i in plan.items:
        travel = "-" if i.travel_minutes_from_previous is None else (
            f"{i.travel_minutes_from_previous} min ({i.travel_basis})")
        targets = ", ".join(i.targets_confirmed + [f"{p} (probable)" for p in i.targets_probable])
        rows.append(f"| {i.day} | {i.start_at:%H:%M}-{i.end_at:%H:%M} | {i.title} | "
                    f"{i.utility:.1f} | {travel} | {i.availability} | {targets or '-'} |")
    return rows


def main() -> int:
    started = datetime.now(timezone.utc)
    fx = load_fixture()
    state = state_from_fixture(fx)
    cands = build_candidates(state.events, state.goals, state.people)
    plan = optimize(cands, state.constraints)
    found = verdicts(cands, state.people, state.constraints)
    graph_note, store = _graph_status()

    lines = [
        "# Probe: antifomo (window 10)",
        "",
        f"- Probe run at: {started.isoformat(timespec='seconds')}",
        "- Source mode: **fixture** (synthetic events and people, labelled `[Fixture]`)",
        f"- Fixture: `{FIXTURE_PATH.relative_to(ROOT)}`, collected_at "
        f"{fx.collected_at.isoformat()}",
        f"- Records: {len(fx.events)} events, {len(fx.people)} people, {len(fx.goals)} goals "
        f"(raw = unique, no dedup needed)",
        "- Status: ok / termination: not_applicable (no network collection in this window)",
        f"- Graph: {graph_note}",
        "- Live behaviour: none claimed. Agents consume normalized data; live quality "
        "depends on windows 01-09.",
        "",
        "## Baseline agenda",
        "",
        *_plan_table(plan),
        "",
        f"Total utility {plan.total_utility}, known event spend {plan.known_cost_usd} USD, "
        f"unknown price for: {', '.join(plan.unknown_cost_event_ids) or 'none'}.",
        "",
        "### Rationale",
        "",
        *[f"- {line}" for line in explain(plan)],
        "",
        "## Anti-FOMO verdicts",
        "",
    ]
    for v in found:
        lines.append(f"- **{v.a} vs {v.b}** -> `{v.chosen}` (margin {v.margin}): {v.text}")
    lines.append("")
    lines.append("## Replanning scenarios")
    errors: list[str] = []
    for spec in list_scenarios():
        out = run_scenario(spec["id"], store=store)
        errors += out["errors"]
        before, after = Plan.model_validate(out["before"]), Plan.model_validate(out["after"])
        lines += [
            "",
            f"### {spec['id']}: {spec['title']}",
            "",
            f"Change: `{out['change']['type']}`; effects: {'; '.join(out['effects'])}",
            f"Changes vs original: {out['diff']['changes']} "
            f"(added {len(out['diff']['added'])}, removed {len(out['diff']['removed'])}, "
            f"moved {len(out['diff']['moved'])})",
            "",
            "Before:",
            "",
            *_plan_table(before),
            "",
            "After:",
            "",
            *_plan_table(after),
            "",
            "Why it changed:",
            "",
            *[f"- {r}" for r in out["diff"]["reasons"]],
        ]
        if out["graph_writes"]:
            lines.append(f"- graph writes: {len(out['graph_writes'])}")
    lines += ["", "## Errors", ""] + ([f"- {e}" for e in errors] or ["- none"])
    OUT.write_text("\n".join(lines) + "\n")
    print(f"wrote {OUT.relative_to(ROOT)} ({len(plan.items)} items, {len(found)} verdicts, "
          f"source_mode=fixture)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
