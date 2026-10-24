"""Provider-neutral ground-travel models (window 11, local adapters around core v0.2).

Core v0.2 has no route schema and `DiscoveryQuery.domain` has no "travel" value, so
these models live here. Every leg carries provider, source_mode and collected_at.
Unknown durations or prices stay None; nothing is filled in from a guess.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import AwareDatetime, Field, HttpUrl, model_validator

from conferge.core.schemas import (
    CoreModel,
    DataMode,
    MoneyString,
    RunReport,
    RunStatus,
    SourceEvidence,
    SourceMode,
)

Mode = Literal["walk", "drive", "rideshare", "bart", "muni", "caltrain", "transit"]
PriceStatus = Literal["exact", "estimate", "unknown"]
DurationStatus = Literal["scheduled", "estimate", "unknown"]
PlaceKind = Literal["airport", "venue", "station", "hotel", "event", "other"]


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Place(CoreModel):
    id: str
    name: str
    kind: PlaceKind = "other"
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    coordinate_precision: Literal["exact", "approximate", "city", "unknown"] = "approximate"
    bart_station: str | None = None
    iata: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    source_url: HttpUrl | None = None


class Price(CoreModel):
    amount: MoneyString | None = None
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    status: PriceStatus = "unknown"
    fare_class: str | None = None
    note: str | None = None

    @model_validator(mode="after")
    def consistent(self) -> Price:
        if self.status == "unknown" and self.amount is not None:
            raise ValueError("unknown price status cannot carry an amount")
        if self.status != "unknown" and self.amount is None:
            raise ValueError("price status requires an amount")
        if self.amount is not None and self.currency is None:
            raise ValueError("currency required when amount exists")
        return self


class RouteLeg(CoreModel):
    from_place: Place
    to_place: Place
    mode: Mode
    departure_local: AwareDatetime | None = None
    arrival_local: AwareDatetime | None = None
    duration_minutes: int | None = Field(default=None, ge=0)
    duration_status: DurationStatus = "unknown"
    distance_m: int | None = Field(default=None, ge=0)
    price: Price = Field(default_factory=Price)
    provider: str
    source_mode: SourceMode
    collected_at: AwareDatetime
    source_url: HttpUrl | None = None
    line: str | None = None
    warnings: list[str] = Field(default_factory=list)
    evidence: list[SourceEvidence] = Field(default_factory=list)

    @model_validator(mode="after")
    def check_times(self) -> RouteLeg:
        if self.departure_local and self.arrival_local and self.arrival_local < self.departure_local:
            raise ValueError("arrival_local must be >= departure_local")
        if self.duration_status == "unknown" and self.duration_minutes is not None:
            raise ValueError("unknown duration status cannot carry minutes")
        return self


class ProviderOutcome(CoreModel):
    """One provider call: candidate legs plus a mandatory run report."""

    legs: list[RouteLeg] = Field(default_factory=list)
    run_report: RunReport
    raw_ref: str | None = None


class RouteOption(CoreModel):
    """An ordered chain of legs from origin to destination."""

    id: str
    label: str
    legs: list[RouteLeg] = Field(min_length=1)
    total_duration_minutes: int | None = None
    total_price: Price = Field(default_factory=Price)
    complete: bool = False
    warnings: list[str] = Field(default_factory=list)


class RoutePlan(CoreModel):
    origin: Place
    destination: Place
    options: list[RouteOption] = Field(default_factory=list)
    source_mode: DataMode
    status: RunStatus
    collected_at: AwareDatetime = Field(default_factory=utcnow)
    reports: list[RunReport] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
