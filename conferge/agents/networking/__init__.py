"""Window 09: smart networking (who to meet, why, where, how) with memory.

The agent class is loaded lazily: ``conferge.agents.planner`` imports helpers
from this package, so an eager import here would be circular.
"""

from typing import Any

from conferge.agents.networking.memory import MemoryBook, met
from conferge.core.schemas import AgentContext, AgentResult


async def run(ctx: AgentContext) -> AgentResult:
    from conferge.agents.networking.agent import run as _run

    return await _run(ctx)


def __getattr__(name: str) -> Any:
    if name == "NetworkingAgent":
        from conferge.agents.networking.agent import NetworkingAgent

        return NetworkingAgent
    raise AttributeError(name)


__all__ = ["MemoryBook", "NetworkingAgent", "met", "run"]
