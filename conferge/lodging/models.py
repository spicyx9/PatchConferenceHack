"""Window-local query model (adapter around the frozen core ``DiscoveryQuery``)."""

from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from conferge.core.schemas import DiscoveryQuery

# GitHub Universe 2026 venue (docs/knowledge/03-demo-scenario.md). Not Moscone.
FORT_MASON = {"id": "venue:fort-mason-center", "name": "Fort Mason Center",
              "lat": 37.8060, "lng": -122.4320}


class Place(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    name: str
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)


class LodgingQuery(BaseModel):
    """Exact-stay query. Dates and adults are mandatory semantics, never defaulted silently."""

    model_config = ConfigDict(extra="forbid")
    lat: float = Field(default=FORT_MASON["lat"], ge=-90, le=90)
    lng: float = Field(default=FORT_MASON["lng"], ge=-180, le=180)
    radius_km: float = Field(default=3.0, gt=0, le=50)
    check_in: date
    check_out: date
    adults: int = Field(default=1, ge=1)
    children: int = Field(default=0, ge=0)
    rooms: int = Field(default=1, ge=1)
    currency: str = Field(default="USD", pattern=r"^[A-Z]{3}$")
    country: str = "us"
    location: str = "San Francisco"
    search_term: str = "hotels near Fort Mason Center San Francisco"
    venue: Place = Field(default_factory=lambda: Place(**FORT_MASON))
    venues: list[Place] = Field(default_factory=list)
    limit: int = Field(default=20, ge=1, le=200)
    verify_top: int = Field(default=15, ge=0, le=50)
    conference_id: str | None = None

    @model_validator(mode="after")
    def _dates(self) -> LodgingQuery:
        if self.check_out <= self.check_in:
            raise ValueError("check_out must follow check_in")
        return self

    @property
    def nights(self) -> int:
        return (self.check_out - self.check_in).days

    def cache_key(self) -> tuple[Any, ...]:
        return (self.check_in, self.check_out, self.adults, self.children, self.rooms,
                self.currency, round(self.lat, 4), round(self.lng, 4), self.radius_km,
                self.location, self.search_term, self.limit)

    @classmethod
    def from_discovery(cls, query: DiscoveryQuery) -> LodgingQuery:
        """Map a core query. Exact dates are required: lodging never guesses a stay."""
        if query.start_date is None or query.end_date is None:
            raise ValueError("lodging discovery needs start_date (check-in) and end_date (check-out)")
        f = dict(query.filters)
        data: dict[str, Any] = {
            "check_in": query.start_date, "check_out": query.end_date,
            "limit": query.limit if query.limit <= 200 else 200,
            "conference_id": query.conference_id,
        }
        if query.latitude is not None and query.longitude is not None:
            data["lat"], data["lng"] = query.latitude, query.longitude
        if query.radius_km:
            data["radius_km"] = query.radius_km
        if query.city:
            data["location"] = query.city
        if query.keywords:
            data["search_term"] = " ".join(query.keywords)
        for key in ("adults", "children", "rooms", "currency", "country", "search_term",
                    "verify_top", "location"):
            if key in f and f[key] is not None:
                data[key] = f[key]
        if "venue" in f and f["venue"]:
            data["venue"] = Place.model_validate(f["venue"])
        if f.get("venues"):
            data["venues"] = [Place.model_validate(v) for v in f["venues"]]
        return cls(**data)

    def to_discovery(self) -> DiscoveryQuery:
        return DiscoveryQuery(
            domain="lodging", conference_id=self.conference_id, city=self.location,
            latitude=self.lat, longitude=self.lng, radius_km=self.radius_km,
            start_date=self.check_in, end_date=self.check_out,
            keywords=[self.search_term], limit=self.limit,
            filters={"adults": self.adults, "children": self.children, "rooms": self.rooms,
                     "currency": self.currency, "country": self.country,
                     "verify_top": self.verify_top, "venue": self.venue.model_dump(),
                     "venues": [v.model_dump() for v in self.venues]},
        )

    def bounding_box(self) -> tuple[float, float, float, float]:
        """(ne_lat, ne_lng, sw_lat, sw_lng) square of side 2 * radius_km."""
        import math

        dlat = self.radius_km / 111.32
        dlng = self.radius_km / (111.32 * max(math.cos(math.radians(self.lat)), 1e-6))
        return self.lat + dlat, self.lng + dlng, self.lat - dlat, self.lng - dlng
