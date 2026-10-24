"""Probe for window 09: run the planner on every available context, write probes/planner.md.

The planner calls no external provider; its output mode is the mode of the
records it ranks. Contexts tried, in order:
1. ``fixtures/planner.json`` (owned by w09, fictional);
2. ``fixtures/demo.json`` (owned by w13, read only, fictional);
3. FalkorDB graph reads (memory + goal paths) when a graph answers on FALKORDB_HOST.
"""

from __future__ import annotations

import asyncio
import json
import os
import socket
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from conferge.agents.planner import PlannerAgent, parse_goals  # noqa: E402
from conferge.core.schemas import AgentContext, AgentResult  # noqa: E402

OUT = ROOT / "probes" / "planner.md"


def _items(block: Any) -> list[Any]:
    return block["items"] if isinstance(block, dict) and "items" in block else list(block or [])


def planner_context() -> AgentContext:
    fx = json.loads((ROOT / "fixtures" / "planner.json").read_text(encoding="utf-8"))
    return AgentContext.model_validate({**fx["context"], "constraints": {"goal_text": fx["goal_text"]}})


def demo_context() -> AgentContext | None:
    path = ROOT / "fixtures" / "demo.json"
    if not path.exists():
        return None
    d = json.loads(path.read_text(encoding="utf-8"))
    return AgentContext.model_validate({
        "conference": d["conference"], "goals": d.get("goals", []), "data_mode": "fixture",
        "events": _items(d["events"]), "people": _items(d["people"]),
        "budget_usd": (d.get("user") or {}).get("budget_usd"),
    })


def graph_store() -> tuple[Any | None, str]:
    host, port = os.getenv("FALKORDB_HOST", "127.0.0.1"), int(os.getenv("FALKORDB_PORT", "6379"))
    try:
        with socket.create_connection((host, port), timeout=0.3):
            pass
    except OSError:
        return None, f"FalkorDB not reachable on {host}:{port}"
    try:
        from conferge.core.store import connect_graph

        store = connect_graph()
        store.graph.query("RETURN 1")
        return store, f"FalkorDB answered on {host}:{port}"
    except Exception as exc:  # noqa: BLE001
        return None, f"FalkorDB port open but query failed: {type(exc).__name__}"


def section(title: str, result: AgentResult, ctx: AgentContext, seconds: float) -> list[str]:
    plan = next((d for d in result.decisions if d.get("type") == "plan"), None)
    lines = [
        f"## {title}", "",
        f"- agent: `{result.agent}`, status **{result.status}**, source_mode **{result.source_mode}**"
        f" (context declared `{ctx.data_mode}`)",
        f"- input: {len(ctx.people)} people, {len(ctx.events)} events, {len(ctx.goals)} goals in context",
        f"- output: {len(result.opportunities)} people opportunities, "
        f"{sum(len(d['items']) for d in plan['days']) if plan else 0} planned items, "
        f"{len(plan['rejected']) if plan else 0} rejected; runtime {seconds * 1000:.0f} ms",
        f"- errors: {result.errors or 'none'}", "",
        "| rank | person | score | presence | where | source |", "|---|---|---|---|---|---|",
    ]
    for i, opp in enumerate(result.opportunities[:10], 1):
        ev = opp.evidence[0] if opp.evidence else None
        src = f"{ev.provider}/{ev.source_mode} @ {ev.collected_at.isoformat() if ev and ev.collected_at else '?'}" if ev else "none"
        lines.append(f"| {i} | {opp.title} | {opp.score} | {opp.presence} | {opp.where or 'unknown'} | {src} |")
    if result.opportunities:
        lines += ["", "Top explanation:", "", f"> {result.opportunities[0].rationale}"]
    if plan:
        lines += ["", "Plan:", ""]
        for day in plan["days"]:
            items = ", ".join(f"{it['start'][11:16]} {it['title']} ({it['score']})" for it in day["items"])
            lines.append(f"- {day['date']}: {items or 'nothing'}")
        for rej in plan["rejected"]:
            lines.append(f"- rejected `{rej['id']}`: {rej['reason']}")
        for warning in plan["warnings"]:
            lines.append(f"- warning: {warning}")
    lines += ["", "Explanations: " + "; ".join(result.explanations), ""]
    return lines


async def main() -> None:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    lines = [
        "# Probe: planner (window 09)", "",
        f"collected_at: {now}", "",
        "The planner and networking agents call no external provider: they rank the records "
        "they are given. No OpenAI key is used; goal parsing is rule based. Every record below "
        "is **fixture** (fictional personas, `.invalid` URLs); nothing here is a live claim.", "",
        "## Goal parser", "",
    ]
    for text in [
        "Fondateur d'un outil dev IA, je vais à GitHub Universe pour rencontrer des investisseurs "
        "seed, des fondateurs d'agents IA et des PM Copilot.",
        "",
    ]:
        goals = parse_goals(text)
        lines.append(f"- `{text or '(empty)'}` -> " + "; ".join(
            f"{g.id} w={g.priority} roles={g.target_roles} topics={g.topics} tags={g.tags}" for g in goals))
    lines.append("")

    runs: list[tuple[str, AgentContext, PlannerAgent]] = [
        ("fixtures/planner.json (w09 fixture)", planner_context(), PlannerAgent())]
    demo = demo_context()
    if demo is not None:
        runs.append(("fixtures/demo.json (w13 fixture, read only)", demo, PlannerAgent()))
    else:
        lines += ["fixtures/demo.json absent: demo context skipped", ""]
    store, graph_note = graph_store()
    lines += [f"Graph: {graph_note}.", ""]
    if store is not None:
        runs.append(("fixtures/planner.json with FalkorDB reads", planner_context(), PlannerAgent(graph=store)))
        if demo is not None:
            runs.append(("fixtures/demo.json with FalkorDB reads (read only)", demo,
                         PlannerAgent(graph=store)))

    for title, ctx, agent in runs:
        start = datetime.now(timezone.utc)
        result = await agent.run(ctx)
        seconds = (datetime.now(timezone.utc) - start).total_seconds()
        lines += section(title, result, ctx, seconds)
        print(f"{title}: {result.status} {result.source_mode} people={len(result.opportunities)}")

    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    asyncio.run(main())
