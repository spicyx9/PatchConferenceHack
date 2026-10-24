"""Inventory of feature windows: what has landed on main and whether it fits the contracts."""

from __future__ import annotations

import importlib
import inspect
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

ROOT = Path(__file__).resolve().parents[2]

Kind = Literal["source", "agent", "graph", "api", "demo", "travel"]


@dataclass(frozen=True)
class Component:
    window: str
    slug: str
    module: str
    kind: Kind
    entry: tuple[str, ...] = ()
    """Attributes expected on the module (class implementing the contract, run, ...)."""
    fixture: str | None = None
    probe: str | None = None


@dataclass
class ComponentStatus:
    component: Component
    present: bool
    detail: str
    contract_ok: bool | None = None
    fixture_present: bool | None = None
    probe_present: bool | None = None
    issues: list[str] = field(default_factory=list)


COMPONENTS: tuple[Component, ...] = (
    Component("01", "luma", "conferge.events.luma", "source", ("LumaSource", "run", "load_fixture"),
              "luma.json", "luma"),
    Component("01", "partiful", "conferge.events.partiful", "source",
              ("PartifulSource", "run", "load_fixture"), "partiful.json", "partiful"),
    Component("02", "eventbrite", "conferge.events.eventbrite", "source",
              ("EventbriteSource", "run", "load_fixture_records"),
              "eventbrite-aggregators.json", "eventbrite-aggregators"),
    Component("02", "aggregators", "conferge.events.aggregators", "source",
              ("AggregatorSource", "run", "load_fixture_records"),
              "eventbrite-aggregators.json", "eventbrite-aggregators"),
    Component("03", "official", "conferge.events.official", "source",
              ("OfficialConferenceSource", "run", "load_fixture"), "official.json", "official"),
    Component("04", "discovery", "conferge.events.discovery", "source",
              ("SerpDiscoverySource", "run", "load_fixture"), "discovery.json", "discovery"),
    Component("05", "lodging", "conferge.lodging", "source", (), "lodging.json", "lodging"),
    Component("06", "flights", "conferge.flights", "source", (), "flights.json", "flights"),
    Component("07", "people", "conferge.people", "source", (), "people.json", "people"),
    Component("08", "graph", "conferge.graph", "graph", ("GraphBundle", "ingest_bundle"),
              "graph.json", "graph"),
    Component("09", "planner", "conferge.agents.planner", "agent", (), "planner.json", "planner"),
    Component("09", "networking", "conferge.agents.networking", "agent", ()),
    Component("10", "antifomo", "conferge.agents.antifomo", "agent", (), "antifomo.json",
              "antifomo"),
    Component("10", "replanner", "conferge.agents.replanner", "agent", ()),
    Component("11", "travel", "conferge.travel.routes", "travel", (), "travel.json", "travel"),
    Component("12", "api", "conferge.api.app", "api", ("create_app",), "api.json", "api"),
    Component("13", "demo", "conferge.demo", "demo", ("DemoPlannerAgent", "replay", "build_world"),
              "demo.json", "demo"),
)


def _is_source_class(obj: Any) -> bool:
    return inspect.isclass(obj) and all(
        inspect.iscoroutinefunction(getattr(obj, name, None))
        for name in ("discover", "fetch_details")
    )


def _is_agent(obj: Any) -> bool:
    run = getattr(obj, "run", None)
    return run is not None and inspect.iscoroutinefunction(run)


def check_component(component: Component, root: Path = ROOT) -> ComponentStatus:
    fixture = (root / "fixtures" / component.fixture).exists() if component.fixture else None
    probe = (
        (root / "scripts" / "probes" / f"{component.probe}.py").exists()
        if component.probe else None
    )
    try:
        module = importlib.import_module(component.module)
    except ModuleNotFoundError as exc:
        if exc.name and component.module.startswith(exc.name):
            return ComponentStatus(component, False, "not merged on main yet",
                                   fixture_present=fixture, probe_present=probe)
        return ComponentStatus(component, False, f"import error: missing {exc.name}",
                               contract_ok=False, fixture_present=fixture, probe_present=probe,
                               issues=[f"import error: missing dependency {exc.name}"])
    except Exception as exc:  # noqa: BLE001 - a broken module is a finding, not a crash
        return ComponentStatus(component, False, f"import error: {type(exc).__name__}",
                               contract_ok=False, fixture_present=fixture, probe_present=probe,
                               issues=[f"import error: {type(exc).__name__}: {exc}"[:200]])
    issues = [f"missing expected attribute {name!r}" for name in component.entry
              if not hasattr(module, name)]
    if component.kind == "source":
        classes = [obj for _, obj in inspect.getmembers(module, _is_source_class)]
        if not classes:
            issues.append("no class with async discover() and fetch_details() (Source contract)")
    if component.kind == "agent":
        candidates = [module, *(obj for _, obj in inspect.getmembers(module, inspect.isclass))]
        if not any(_is_agent(c) for c in candidates):
            issues.append("no async run(AgentContext) found (Agent contract)")
    if fixture is False and component.kind in {"source", "graph", "api", "demo", "travel"}:
        issues.append(f"fixture fixtures/{component.fixture} missing")
    if probe is False:
        issues.append(f"probe scripts/probes/{component.probe}.py missing")
    return ComponentStatus(component, True, component.module, contract_ok=not issues,
                           fixture_present=fixture, probe_present=probe, issues=issues)


def inventory(root: Path = ROOT) -> list[ComponentStatus]:
    return [check_component(c, root) for c in COMPONENTS]
