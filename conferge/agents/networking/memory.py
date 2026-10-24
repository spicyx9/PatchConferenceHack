"""User memory for networking: ``met()`` records and immediately re-ranks.

In-process ``MemoryBook`` always works; when a ``GraphStore`` is given the
memory is also persisted through window 08 ``record_memory`` (GraphStore MERGE
only). A failed graph write is reported, never hidden.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

from conferge.core.schemas import AgentContext, AgentResult

MemoryKind = Literal["MET", "CONTACTED"]


@dataclass
class MemoryEntry:
    kind: MemoryKind
    person_id: str
    note: str | None
    at: datetime


@dataclass
class MemoryBook:
    entries: dict[str, dict[str, MemoryEntry]] = field(default_factory=dict)

    def record(self, user_id: str, person_id: str, kind: MemoryKind = "MET",
               note: str | None = None, at: datetime | None = None) -> MemoryEntry:
        when = at or datetime.now(timezone.utc)
        if when.tzinfo is None:
            raise ValueError("memory timestamp must be timezone-aware")
        entry = MemoryEntry(kind, person_id, note, when)
        self.entries.setdefault(user_id, {})[person_id] = entry
        return entry

    def excluded(self, user_id: str) -> set[str]:
        return set(self.entries.get(user_id, {}))


def persist(store: Any, entry: MemoryEntry, user_id: str) -> str | None:
    """Write to FalkorDB via window 08; returns an error string or None."""
    try:
        from conferge.graph import record_memory
    except Exception as exc:  # noqa: BLE001
        return f"graph memory not persisted: conferge.graph unavailable ({type(exc).__name__})"
    try:
        record_memory(store, user_id, entry.kind, "Person", entry.person_id,
                      note=entry.note, at=entry.at)
    except Exception as exc:  # noqa: BLE001
        return f"graph memory not persisted: {type(exc).__name__}"
    return None


async def met(agent: Any, ctx: AgentContext, person_id: str, note: str | None = None,
              *, store: Any | None = None) -> AgentResult:
    """Record that ``ctx.user_id`` met ``person_id`` and return the new ranking."""
    entry = agent.memory.record(ctx.user_id, person_id, "MET", note)
    error = persist(store, entry, ctx.user_id) if store is not None else None
    result: AgentResult = await agent.run(ctx)
    if error:
        result = result.model_copy(update={
            "errors": [*result.errors, error],
            "status": "degraded" if result.status == "ok" else result.status,
        })
    return result
