"""Interfaces implemented by independent workstreams; owned by window 0."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from conferge.core.schemas import (
    AgentContext,
    AgentResult,
    DiscoveryQuery,
    DiscoveryResult,
    SourceRecord,
    SourceRef,
)


@runtime_checkable
class Source(Protocol):
    """Network-backed or fixture-backed source; methods are async."""

    async def discover(self, query: DiscoveryQuery) -> DiscoveryResult: ...

    async def fetch_details(self, ref: SourceRef) -> SourceRecord: ...


@runtime_checkable
class Agent(Protocol):
    """Goal-driven reasoning stage; accepts normalized context only."""

    async def run(self, ctx: AgentContext) -> AgentResult: ...
