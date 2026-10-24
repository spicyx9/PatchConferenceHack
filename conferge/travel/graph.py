"""Write route proximity to FalkorDB through core GraphStore only.

Places become `Venue` nodes; each leg with a known duration becomes a `NEAR` edge
carrying mode, minutes, provider, source_mode, confidence and observed_at. Legs with
unknown duration are skipped, never written as zero; so are legs without a source URL,
since every graph edge must cite its evidence.
"""

from __future__ import annotations

from collections.abc import Iterable

from conferge.core.store import GraphStore
from conferge.travel.models import Place, RoutePlan

_CONFIDENCE = {"scheduled": 0.9, "estimate": 0.6}


def _node(store: GraphStore, place: Place, written: set[str]) -> None:
    if place.id in written:
        return
    store.merge_node("Venue", place.id, {
        "name": place.name, "kind": place.kind, "latitude": place.latitude,
        "longitude": place.longitude, "coordinate_precision": place.coordinate_precision,
    })
    written.add(place.id)


def write_plans(store: GraphStore, plans: Iterable[RoutePlan]) -> int:
    """Return the number of NEAR edges merged."""
    written: set[str] = set()
    edges = 0
    for plan in plans:
        for option in plan.options:
            for leg in option.legs:
                if leg.duration_minutes is None or leg.duration_status == "unknown":
                    continue
                urls = [str(u) for u in [leg.source_url, *(e.source_url for e in leg.evidence)] if u]
                if not urls:
                    continue
                _node(store, leg.from_place, written)
                _node(store, leg.to_place, written)
                # One NEAR edge per pair; properties are namespaced by mode so a
                # walk and a drive leg between the same places do not overwrite each other.
                m = leg.mode
                store.merge_edge("Venue", leg.from_place.id, "NEAR", "Venue", leg.to_place.id, {
                    f"{m}_minutes": leg.duration_minutes,
                    f"{m}_source": leg.provider, f"{m}_source_mode": leg.source_mode,
                    f"{m}_duration_status": leg.duration_status,
                    f"{m}_confidence": _CONFIDENCE.get(leg.duration_status, 0.5),
                    f"{m}_observed_at": leg.collected_at.isoformat(),
                    "evidence_ids": list(dict.fromkeys(urls)),
                })
                edges += 1
    return edges
