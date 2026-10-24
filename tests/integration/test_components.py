from __future__ import annotations

from conferge.integration.components import COMPONENTS, Component, check_component, inventory


def test_inventory_covers_every_window() -> None:
    statuses = inventory()
    assert {s.component.window for s in statuses} >= {
        "01", "02", "03", "04", "05", "06", "07", "08", "09", "10", "11", "12", "13",
    }
    assert len(statuses) == len(COMPONENTS)


def test_merged_core_components_satisfy_contracts() -> None:
    by_slug = {s.component.slug: s for s in inventory()}
    for slug in ("luma", "partiful", "eventbrite", "aggregators", "official", "discovery",
                 "graph", "antifomo", "replanner", "travel", "api", "demo"):
        status = by_slug[slug]
        assert status.present, slug
        assert status.contract_ok, (slug, status.issues)


def test_absent_module_is_reported_not_merged() -> None:
    status = check_component(Component("99", "ghost", "conferge.ghost_window", "source"))
    assert not status.present
    assert status.contract_ok is None
    assert status.detail == "not merged on main yet"


def test_module_without_source_class_breaks_contract() -> None:
    status = check_component(Component("99", "bad", "conferge.core.schemas", "source",
                                       ("run",)))
    assert status.present
    assert status.contract_ok is False
    assert any("Source contract" in i for i in status.issues)
    assert any("'run'" in i for i in status.issues)


def test_agent_contract_detects_async_run() -> None:
    status = check_component(Component("13", "demo-agent", "conferge.demo", "agent"))
    assert status.contract_ok, status.issues
