"""Cross-session user memory (MET, ATTENDED, SKIPPED, CONTACTED).

No ``User`` label exists in the core allow-list, so each memory is a
``(:Meeting {user_id, kind})`` node linked to its target: ``MET`` for a met
person, ``INVOLVES`` otherwise. Ranking queries read these to drop people the
user already met or contacted. Writes go through ``GraphStore`` only.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from conferge.core.store import GraphStore
from conferge.graph.schema import memory_id

MemoryKind = Literal["MET", "ATTENDED", "SKIPPED", "CONTACTED"]
TargetKind = Literal["Person", "Event", "Company"]


def record_memory(store: GraphStore, user_id: str, kind: MemoryKind, target_kind: TargetKind,
                  target_id: str, note: str | None = None,
                  at: datetime | None = None) -> str:
    if kind not in ("MET", "ATTENDED", "SKIPPED", "CONTACTED"):
        raise ValueError(f"unsupported memory kind: {kind!r}")
    if kind == "MET" and target_kind != "Person":
        raise ValueError("MET memory must target a Person")
    when = at or datetime.now(timezone.utc)
    if when.tzinfo is None:
        raise ValueError("memory timestamp must be timezone-aware")
    node_id = memory_id(user_id, kind, target_id)
    props: dict[str, object] = {
        "user_id": user_id, "kind": kind, "at": when.isoformat(), "name": f"{kind} {target_id}",
        "source": "user", "source_mode": "live", "observed_at": when.isoformat(),
    }
    if note:
        props["note"] = note
    store.merge_node("Meeting", node_id, props)
    store.merge_edge("Meeting", node_id, "MET" if kind == "MET" else "INVOLVES",
                     target_kind, target_id,
                     {"source": "user", "source_mode": "live", "confidence": 1.0,
                      "observed_at": when.isoformat(), "verification": "user_reported"})
    return node_id
