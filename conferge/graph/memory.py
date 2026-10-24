"""Cross-session user memory (MET, ATTENDED, SKIPPED, CONTACTED).

No ``User`` label exists in the core allow-list, so each memory is a
``(:Meeting {user_id, kind, at_ms})`` node linked to its target: ``MET`` for a met
person, ``INVOLVES`` otherwise. Ranking queries read these to drop people the
user already met or contacted. Writes go through ``GraphStore`` only.

Each call is one occurrence: the node id hashes (user, kind, target, at_ms), so
meeting the same person twice keeps two memories instead of overwriting one.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Literal, get_args

from conferge.core.store import GraphStore

MemoryKind = Literal["MET", "ATTENDED", "SKIPPED", "CONTACTED"]
TargetKind = Literal["Person", "Event", "Company"]
SkipReason = Literal["conflict", "not_interested", "cancelled"]


def occurrence_id(user_id: str, kind: str, target_id: str, at_ms: int) -> str:
    digest = hashlib.sha256(f"{user_id}|{kind}|{target_id}|{at_ms}".encode()).hexdigest()[:20]
    return f"memory:{digest}"


def record_memory(store: GraphStore, user_id: str, kind: MemoryKind, target_kind: TargetKind,
                  target_id: str, note: str | None = None,
                  at: datetime | None = None, reason: SkipReason | None = None) -> str:
    if kind not in ("MET", "ATTENDED", "SKIPPED", "CONTACTED"):
        raise ValueError(f"unsupported memory kind: {kind!r}")
    if kind == "MET" and target_kind != "Person":
        raise ValueError("MET memory must target a Person")
    if kind == "SKIPPED" and reason not in get_args(SkipReason):
        raise ValueError(f"SKIPPED needs a reason in {get_args(SkipReason)}, got {reason!r}")
    if kind != "SKIPPED" and reason is not None:
        raise ValueError("only SKIPPED memories carry a reason")
    when = at or datetime.now(timezone.utc)
    if when.tzinfo is None:
        raise ValueError("memory timestamp must be timezone-aware")
    at_ms = int(when.timestamp() * 1000)
    node_id = occurrence_id(user_id, kind, target_id, at_ms)
    props: dict[str, object] = {
        "user_id": user_id, "kind": kind, "at": when.isoformat(), "at_ms": at_ms,
        "target_id": target_id, "name": f"{kind} {target_id}",
        "source": "user", "source_mode": "live", "observed_at": when.isoformat(),
    }
    if note:
        props["note"] = note
    if reason:
        props["reason"] = reason
    store.merge_node("Meeting", node_id, props)
    store.merge_edge("Meeting", node_id, "MET" if kind == "MET" else "INVOLVES",
                     target_kind, target_id,
                     {"source": "user", "source_mode": "live", "confidence": 1.0,
                      "observed_at": when.isoformat(), "verification": "user_reported"})
    return node_id
