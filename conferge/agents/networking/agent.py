"""Networking agent: people ranking only, same scoring as the planner."""

from __future__ import annotations

from conferge.agents.planner.agent import PlannerAgent
from conferge.core.schemas import AgentContext, AgentResult


class NetworkingAgent(PlannerAgent):
    """Who to meet, why, where, how; no day plan."""

    name = "networking-w09"

    def __init__(self, **kwargs: object) -> None:
        kwargs.setdefault("include_plan", False)
        super().__init__(**kwargs)  # type: ignore[arg-type]


_DEFAULT = NetworkingAgent()


async def run(ctx: AgentContext) -> AgentResult:
    return await _DEFAULT.run(ctx)
