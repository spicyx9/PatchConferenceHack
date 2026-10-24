"""GeoJSON for a Leaflet map: place markers and leg segments.

Leg geometry is a straight segment between endpoints (providers are called with
overview=false), flagged `geometry: "straight_segment"` so the UI never presents it
as a routed path.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from conferge.travel.models import Place, RoutePlan


def _point(place: Place) -> dict[str, Any]:
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [place.longitude, place.latitude]},
        "properties": {
            "id": place.id, "name": place.name, "kind": place.kind,
            "coordinate_precision": place.coordinate_precision,
        },
    }


def map_features(plans: Iterable[RoutePlan], extra_places: Iterable[Place] = ()) -> dict[str, Any]:
    places: dict[str, Place] = {p.id: p for p in extra_places}
    lines: list[dict[str, Any]] = []
    for plan in plans:
        places.setdefault(plan.origin.id, plan.origin)
        places.setdefault(plan.destination.id, plan.destination)
        for option in plan.options:
            for index, leg in enumerate(option.legs):
                places.setdefault(leg.from_place.id, leg.from_place)
                places.setdefault(leg.to_place.id, leg.to_place)
                lines.append({
                    "type": "Feature",
                    "geometry": {"type": "LineString", "coordinates": [
                        [leg.from_place.longitude, leg.from_place.latitude],
                        [leg.to_place.longitude, leg.to_place.latitude],
                    ]},
                    "properties": {
                        "option_id": option.id, "leg_index": index, "mode": leg.mode,
                        "provider": leg.provider, "source_mode": leg.source_mode,
                        "duration_minutes": leg.duration_minutes,
                        "duration_status": leg.duration_status,
                        "price_amount": leg.price.amount, "price_status": leg.price.status,
                        "geometry": "straight_segment",
                    },
                })
    return {"type": "FeatureCollection",
            "features": [_point(p) for p in places.values()] + lines}
