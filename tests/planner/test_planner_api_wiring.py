"""API discovery of the w09 agents and the networking variant."""

from __future__ import annotations

from planner_helpers import load_fixture, make_ctx, ranking

from conferge.api import providers
from conferge.core.schemas import AgentResult

EXPECTED = load_fixture()["expected"]["people_ranking"]


def test_discover_providers_finds_planner_and_networking() -> None:
    found = providers.discover_providers()
    status = {s.name: s for s in found.statuses}
    for name in ("planner", "networking"):
        assert name in found.agents
        assert status[name].available, status[name].detail


async def test_run_agent_returns_result_with_opportunities() -> None:
    found = providers.discover_providers()
    for name in ("planner", "networking"):
        res = await providers.run_agent(found.agents[name], make_ctx())
        assert isinstance(res, AgentResult)
        assert res.opportunities
        assert ranking(res) == EXPECTED[: len(res.opportunities)]


async def test_planner_run_has_plan_networking_does_not() -> None:
    from conferge.agents.networking import NetworkingAgent
    from conferge.agents.planner import PlannerAgent

    planner = await PlannerAgent(people_limit=None).run(make_ctx())
    net = await NetworkingAgent(people_limit=None).run(make_ctx())
    assert any(d.get("type") == "plan" for d in planner.decisions)
    assert not any(d.get("type") == "plan" for d in net.decisions)
    assert net.agent == "networking-w09"
    assert ranking(net) == ranking(planner)
    assert not any(e.startswith("plan:") for e in net.explanations)


async def test_module_level_networking_run() -> None:
    from conferge.agents import networking

    res = await networking.run(make_ctx())
    assert isinstance(res, AgentResult)
    assert not any(d.get("type") == "plan" for d in res.decisions)
