"""End-to-end run: request -> normalized sources -> planning -> graph -> API.

``run_e2e(mode="fixture")`` is fully offline and deterministic enough for CI.
``run_e2e(mode="live")`` calls public endpoints; a failed source stays failed
unless ``fallback_fixture=True`` was passed, in which case the replacement
slice is labelled fixture and the report says so.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

from conferge.core.schemas import AgentContext, AgentResult, Goal, Opportunity
from conferge.core.store import GraphStore
from conferge.integration import checks
from conferge.integration.assemble import Assembly, assemble
from conferge.integration.components import ComponentStatus, inventory
from conferge.integration.memgraph import MemoryGraph
from conferge.integration.sources import SourceSlice, fixture_slices, live_slices
from conferge.integration.stays_flights import collect_stays_flights

Outcome = Literal["pass", "warn", "fail", "skip"]


@dataclass
class StageResult:
    name: str
    outcome: Outcome
    detail: str
    findings: list[str] = field(default_factory=list)
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class E2EReport:
    mode: str
    started_at: datetime
    finished_at: datetime | None = None
    stages: list[StageResult] = field(default_factory=list)
    components: list[ComponentStatus] = field(default_factory=list)
    slices: list[SourceSlice] = field(default_factory=list)
    mismatches: list[str] = field(default_factory=list)
    data_mode: str = "fixture"

    @property
    def passed(self) -> bool:
        return all(s.outcome != "fail" for s in self.stages)

    def stage(self, name: str) -> StageResult | None:
        return next((s for s in self.stages if s.name == name), None)


def _outcome(ok: bool, warn: bool = False) -> Outcome:
    return "fail" if not ok else ("warn" if warn else "pass")


# -- stages ---------------------------------------------------------------------------


def _stage_inventory(report: E2EReport) -> None:
    report.components = inventory()
    present = [c for c in report.components if c.present]
    broken = [c for c in report.components if c.contract_ok is False]
    findings = [f"w{c.component.window} {c.component.slug}: {i}"
                for c in report.components for i in c.issues]
    loaders = {c.component.slug: [n for n in c.component.entry if n.startswith("load_fixture")]
               for c in present if c.component.kind == "source"}
    names = {n for v in loaders.values() for n in v}
    if len(names) > 1:
        report.mismatches.append(
            "fixture loaders are not uniform: "
            + ", ".join(f"{k}.{v[0]}" for k, v in sorted(loaders.items()) if v)
            + " (load_fixture returns DiscoveryResult/OfficialCollection, "
            "load_fixture_records returns list[SourceRecord] without RunReport)"
        )
    missing = [f"w{c.component.window} {c.component.slug}" for c in report.components
               if not c.present and c.contract_ok is None]
    report.stages.append(StageResult(
        "inventory", _outcome(not broken, bool(missing)),
        f"{len(present)}/{len(report.components)} components merged; "
        f"not merged: {', '.join(missing) or 'none'}",
        findings,
    ))


async def _collect(mode: str, fallback_fixture: bool, timeout: float,
                   names: list[str] | None) -> list[SourceSlice]:
    if mode == "fixture":
        return fixture_slices(names)
    live = await live_slices(names, timeout=timeout)
    if not fallback_fixture:
        return live
    out = []
    for s in live:
        if s.status == "failed" or not s.count:
            replacement = fixture_slices([s.name])
            for r in replacement:
                r.warnings.insert(0, f"live failed ({'; '.join(s.errors)[:160]}); "
                                     "explicit fixture fallback")
            out.append(s)
            out.extend(replacement)
        else:
            out.append(s)
    return out


def _usable(slices: list[SourceSlice]) -> list[SourceSlice]:
    """Slices whose records enter the dataset (failed live slices carry none)."""
    return [s for s in slices if s.count]


def _stage_sources(report: E2EReport, slices: list[SourceSlice]) -> None:
    report.slices = slices
    findings = [f"{s.name} [{s.attempted}]: {e}" for s in slices for e in s.errors]
    usable = _usable(slices)
    lines = ", ".join(f"{s.name}={s.count} {s.source_mode}/{s.status}" for s in slices)
    has_failed = any(s.status == "failed" for s in slices)
    report.stages.append(StageResult(
        "sources", _outcome(bool(usable), has_failed or any(s.status == "degraded" for s in slices)),
        lines or "no source", findings,
    ))


def _stage_checks(report: E2EReport, assembly: Assembly) -> None:
    usable = _usable(report.slices)
    results = [checks.provenance(usable), checks.labels(report.slices),
               checks.relations(assembly.events)]
    for r in results:
        report.stages.append(StageResult(f"check:{r.name}", _outcome(r.passed), r.detail,
                                         r.findings[:50], {"total_findings": len(r.findings)}))
    report.stages.append(StageResult(
        "check:dedup", _outcome(True, bool(assembly.duplicates)),
        f"{len(assembly.events)} events, {len(assembly.people)} people kept; "
        f"{len(assembly.duplicates)} duplicates dropped (first record kept, none merged)",
        assembly.duplicates[:50],
    ))
    report.mismatches.extend(assembly.warnings)


def _agents() -> dict[str, Any]:
    from conferge.api import providers
    from conferge.demo import DemoPlannerAgent

    found: dict[str, Any] = {"demo-planner (w13)": DemoPlannerAgent()}
    for name, agent in providers.discover_providers().agents.items():
        found[f"{name} (merged)"] = agent
    return found


async def _run_agent(agent: Any, ctx: AgentContext) -> AgentResult:
    from conferge.api import providers

    return await providers.run_agent(agent, ctx)


async def _stage_planning(report: E2EReport, assembly: Assembly,
                          goals: list[Goal]) -> list[Opportunity]:
    mode = assembly.data_mode
    ctx = AgentContext(
        conference=assembly.conference, goals=goals,
        data_mode=mode if mode in {"live", "cached", "fixture", "mixed"} else "mixed",
        events=assembly.events, people=assembly.people,
        budget_usd=assembly.demo.user.get("budget_usd"),
    )
    best: list[Opportunity] = []
    findings: list[str] = []
    lines: list[str] = []
    ok = True
    for name, agent in _agents().items():
        run_ctx = ctx
        if "replanner" in name:
            # The replanner reacts to a change; give it a visible simulation on
            # the top-ranked event so the minimal-change path is exercised.
            target = next((o.event_id for o in best if o.event_id), None) or next(
                (e.id for e in assembly.events if e.start_at), None)
            change = {"type": "sold_out", "event_id": target, "source_mode": "fixture",
                      "note": "w15 SIMULATION: not an observed change"}
            run_ctx = ctx.model_copy(update={"constraints": {"change": change},
                                             "opportunities": best})
        try:
            result = await _run_agent(agent, run_ctx)
        except Exception as exc:  # noqa: BLE001 - one agent failing is a finding
            ok = False
            findings.append(f"{name}: raised {type(exc).__name__}: {exc}"[:200])
            continue
        check = checks.opportunities(result.opportunities, assembly.people, assembly.events,
                                     mode, result.source_mode)
        findings += [f"{name}: {f}" for f in check.findings[:20]]
        findings += [f"{name}: {e}" for e in result.errors]
        lines.append(f"{name}: {result.status}, {len(result.opportunities)} opportunities, "
                     f"source_mode={result.source_mode}")
        ok = ok and check.passed and result.status != "failed"
        if not best and result.opportunities:
            best = result.opportunities
    report.stages.append(StageResult("planning", _outcome(ok and bool(best)),
                                     "; ".join(lines) or "no agent", findings,
                                     {"top": [o.title for o in best[:5]]}))
    return best


def _skip_reasons(skipped: list[str]) -> dict[str, int]:
    """Group w08 skipped-edge messages by edge type and reason, without record ids."""
    out: dict[str, int] = {}
    for line in skipped:
        edge = line.split(" ", 1)[0]
        reason = line.rsplit(": ", 1)[-1] if ": " in line else "unspecified"
        key = f"{edge}: {reason}"
        out[key] = out.get(key, 0) + 1
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))


def _stage_graph(report: E2EReport, assembly: Assembly, goals: list[Goal],
                 opps: list[Opportunity]) -> None:
    from conferge.graph import GraphBundle, ingest_bundle

    graph = MemoryGraph()
    mode = assembly.data_mode
    bundle = GraphBundle(
        source_mode="live" if mode == "live" else "fixture",
        note=f"w15 integration run, data_mode={mode}",
        conference=assembly.conference, companies=assembly.companies,
        people=assembly.people, events=assembly.events, goals=goals,
        opportunities=[o for o in opps if set(o.goal_ids) <= {g.id for g in goals}],
        lodging=assembly.demo.stays, flights=assembly.demo.flights,
    )
    try:
        ingest = ingest_bundle(GraphStore(graph), bundle)
    except Exception as exc:  # noqa: BLE001
        report.stages.append(StageResult("graph", "fail", f"ingest raised {type(exc).__name__}",
                                         [str(exc)[:300]]))
        return
    no_mode = graph.nodes_missing("source_mode")
    findings = [f"dangling edge (FalkorDB would silently drop it): {d}"
                for d in graph.dangling[:30]]
    findings += [f"non-GraphStore statement: {q}" for q in graph.refused]
    findings += [f"node without source_mode: {n}" for n in no_mode[:20]]
    reasons = _skip_reasons(ingest.skipped_edges)
    findings += [f"skipped edges: {reason} x{n}" for reason, n in reasons.items()]
    for reason, n in reasons.items():
        report.mismatches.append(f"graph ingest skipped {n} edges: {reason}")
    if graph.dangling:
        report.mismatches.append(f"graph: {len(graph.dangling)} edges point at nodes never merged")
    report.stages.append(StageResult(
        "graph", _outcome(not graph.refused and not no_mode, bool(graph.dangling or
                                                                  ingest.skipped_edges)),
        f"{sum(graph.count_nodes().values())} nodes, {sum(graph.count_edges().values())} edges "
        f"via GraphStore; {len(ingest.skipped_edges)} skipped, {len(graph.dangling)} dangling",
        findings, {"nodes": graph.count_nodes(), "edges": graph.count_edges()},
    ))


def _stage_travel(report: E2EReport) -> None:
    """w11 ground travel: labelled fixture replay plus map rendering (no network)."""
    try:
        from conferge.travel.fixture import load_fixture
        from conferge.travel.map import map_features
    except ImportError:
        report.stages.append(StageResult("travel", "skip", "w11 travel not merged"))
        return
    findings: list[str] = []
    try:
        plans = load_fixture(explicit_opt_in=True)
        features = map_features(plans)
    except Exception as exc:  # noqa: BLE001
        report.stages.append(StageResult("travel", "fail",
                                         f"travel fixture failed: {type(exc).__name__}",
                                         [str(exc)[:200]]))
        return
    legs = [leg for plan in plans for opt in plan.options for leg in opt.legs]
    for plan in plans:
        if plan.source_mode != "fixture":
            findings.append(f"plan {plan.origin.name}->{plan.destination.name}: "
                            f"source_mode={plan.source_mode}")
    findings += [f"leg {leg.provider} {leg.mode}: source_mode={leg.source_mode}"
                 for leg in legs if leg.source_mode != "fixture"]
    report.stages.append(StageResult(
        "travel", _outcome(not findings and bool(plans)),
        f"{len(plans)} route plans, {len(legs)} legs, all fixture-labelled; "
        f"{len(features.get('features', []))} map features",
        findings,
    ))


_API_GETS = ("/health", "/api/v1/sources", "/api/v1/conference", "/api/v1/plan",
             "/api/v1/people", "/api/v1/events", "/api/v1/sessions", "/api/v1/stays",
             "/api/v1/flights", "/api/v1/travel", "/api/v1/travel/map", "/api/v1/graph",
             "/api/v1/scenarios", "/api/v1/roi")


def _stage_api(report: E2EReport, demo: Any, expected_mode: str, *, name: str = "api",
               backup: bool = False) -> None:
    from fastapi.testclient import TestClient

    from conferge.api import providers
    from conferge.api.app import create_app

    app = create_app(data=demo, found=providers.discover_providers(), graph_probe=False)
    # stays/flights may be live while events are fixture: their own endpoint may say live
    live_paths = {f"/api/v1/{name}" for name in ("stays", "flights")
                  if demo.domains[name].source_mode == "live"}
    findings: list[str] = []
    calls = 0
    with TestClient(app) as client:
        def check(method: str, path: str, **kwargs: Any) -> dict[str, Any] | None:
            nonlocal calls
            calls += 1
            resp = client.request(method, path, **kwargs)
            if resp.status_code != 200:
                findings.append(f"{method} {path}: HTTP {resp.status_code} {resp.text[:120]}")
                return None
            body = resp.json()
            label = body.get("data_source")
            if label == "live" and (backup or (expected_mode != "live"
                                               and path not in live_paths)):
                findings.append(f"{method} {path}: labelled live over {expected_mode} data")
            return body

        for path in _API_GETS:
            check("GET", path)
        check("POST", "/api/v1/goal", json={"text": demo.demo_goal_text})
        people = check("GET", "/api/v1/people") or {}
        first = next(iter(people.get("people") or []), None)
        if first and first.get("person_ids"):
            pid = first["person_ids"][0]
            check("GET", "/api/v1/graph/path", params={"person": pid})
            check("POST", "/api/v1/met", json={"person_id": pid})
        scenarios = (check("GET", "/api/v1/scenarios") or {}).get("items") or []
        if scenarios:
            check("POST", "/api/v1/simulate-change", json={"scenario_id": scenarios[0]["id"]})
        else:
            findings.append("no scenario resolvable against assembled events")
        check("POST", "/api/v1/reset")
    report.stages.append(StageResult(name, _outcome(not findings),
                                     f"{calls} calls, {len(findings)} problems", findings))


def _stage_demo_backup(report: E2EReport) -> None:
    from conferge.api.data import load_fixture as load_api_fixture
    from conferge.demo import replay

    findings = []
    try:
        result = replay()
        if result.get("source_mode") != "fixture":
            findings.append(f"w13 replay labelled {result.get('source_mode')}")
        if not result.get("top_people"):
            findings.append("w13 replay produced no top people")
    except Exception as exc:  # noqa: BLE001
        findings.append(f"w13 replay raised {type(exc).__name__}: {exc}"[:200])
    report.stages.append(StageResult("demo-backup:w13-replay", _outcome(not findings),
                                     "deterministic offline replay of fixtures/demo.json",
                                     findings))
    try:
        backup = load_api_fixture()
    except Exception as exc:  # noqa: BLE001
        report.stages.append(StageResult("demo-backup:api-fixture", "fail",
                                         f"fixtures/api.json failed: {type(exc).__name__}"))
        return
    _stage_api(report, backup, "fixture", name="demo-backup:api-fixture", backup=True)


def run_e2e_sync(*args: Any, **kwargs: Any) -> E2EReport:
    return asyncio.run(run_e2e(*args, **kwargs))


async def run_e2e(mode: Literal["fixture", "live"] = "fixture", *,
                  fallback_fixture: bool = False, timeout: float = 90.0,
                  sources: list[str] | None = None, include_backup: bool = True) -> E2EReport:
    from conferge.api.logic import parse_goals

    report = E2EReport(mode=mode, started_at=datetime.now(timezone.utc))
    _stage_inventory(report)
    _stage_sources(report, await _collect(mode, fallback_fixture, timeout, sources))
    travel = await collect_stays_flights(timeout) if mode == "live" else None
    assembly = assemble(_usable(report.slices), travel)
    report.data_mode = assembly.data_mode
    _stage_checks(report, assembly)
    goals = parse_goals(assembly.demo.demo_goal_text)
    opps = await _stage_planning(report, assembly, goals)
    _stage_graph(report, assembly, goals, opps)
    _stage_travel(report)
    _stage_api(report, assembly.demo, assembly.data_mode)
    if include_backup:
        _stage_demo_backup(report)
    report.finished_at = datetime.now(timezone.utc)
    return report


__all__ = ["E2EReport", "StageResult", "run_e2e", "run_e2e_sync"]
