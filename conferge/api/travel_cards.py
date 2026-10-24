"""Explicit presentation view over domain-local adapters, retaining provenance."""

from typing import Any


def view(item: Any) -> dict[str, Any]:
    details = getattr(item, "card_details", None)
    ev = item.evidence[0] if item.evidence else None
    return {
        **item.model_dump(mode="json"),
        "card_details": details.model_dump(mode="json") if details is not None else {},
        "source_mode": ev.source_mode if ev else "unknown",
        "collected_at": ev.collected_at.isoformat() if ev and ev.collected_at else None,
    }
