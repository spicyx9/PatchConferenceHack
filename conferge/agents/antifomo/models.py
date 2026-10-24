"""Local planning models for window 10 (anti-FOMO + replanning).

These wrap the frozen ``conferge.core.schemas`` objects; they never replace them.
A candidate is a normalized ``Event`` plus a utility score and its breakdown.
"""

from __future__ import annotations

from datetime import time
from decimal import Decimal
from typing import Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from conferge.core.schemas import Event, SourceMode

Availability = Literal["registration_link_found", "no_registration_evidence"]
TravelBasis = Literal["first_of_day", "same_venue", "haversine", "unknown_default"]
RejectCode = Literal[
    "time_unknown", "unavailable", "excluded_by_user", "blocked_slot", "outside_daily_window",
    "conflicts_with_fixed", "conflict", "day_full", "low_utility", "over_budget",
    "missing_registration_evidence",
]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TimeSlot(_Model):
    """Fixed appointment or unavailability (flight, meeting, hotel check-in)."""

    id: str
    label: str
    start: AwareDatetime
    end: AwareDatetime

    @model_validator(mode="after")
    def _order(self) -> TimeSlot:
        if self.end <= self.start:
            raise ValueError("TimeSlot.end must follow start")
        return self


class Constraints(_Model):
    timezone: str = "America/Los_Angeles"
    max_per_day: int = Field(default=6, ge=1)
    day_start: time | None = None
    day_end: time | None = None
    blocked: list[TimeSlot] = Field(default_factory=list)
    fixed_event_ids: list[str] = Field(default_factory=list)
    excluded_event_ids: list[str] = Field(default_factory=list)
    budget_usd: Decimal | None = Field(default=None, ge=0)
    require_registration_evidence: bool = False
    change_penalty: float = Field(default=8.0, ge=0)
    default_travel_minutes: int = Field(default=20, ge=0)
    same_venue_buffer_minutes: int = Field(default=5, ge=0)
    travel_overhead_minutes: int = Field(default=8, ge=0)
    travel_speed_kmh: float = Field(default=18.0, gt=0)


class Candidate(_Model):
    event: Event
    utility: float = Field(ge=0, le=100)
    breakdown: dict[str, float] = Field(default_factory=dict)
    goal_ids: list[str] = Field(default_factory=list)
    targets_confirmed: list[str] = Field(default_factory=list)
    targets_probable: list[str] = Field(default_factory=list)
    target_companies: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)
    cost_usd: Decimal | None = None
    score_source: Literal["antifomo_utility", "planner_opportunity"] = "antifomo_utility"

    @property
    def id(self) -> str:
        return self.event.id


class PlanItem(_Model):
    event_id: str
    title: str
    day: str
    start_at: AwareDatetime
    end_at: AwareDatetime
    venue_name: str | None = None
    utility: float
    travel_minutes_from_previous: int | None = None
    travel_basis: TravelBasis = "first_of_day"
    availability: Availability
    fixed: bool = False
    kept_from_original: bool | None = None
    targets_confirmed: list[str] = Field(default_factory=list)
    targets_probable: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)
    source_mode: SourceMode | None = None
    collected_at: AwareDatetime | None = None
    warnings: list[str] = Field(default_factory=list)


class Rejection(_Model):
    event_id: str
    title: str
    code: RejectCode
    reason: str
    blocking_event_id: str | None = None
    utility: float | None = None


class Plan(_Model):
    items: list[PlanItem] = Field(default_factory=list)
    rejected: list[Rejection] = Field(default_factory=list)
    total_utility: float = 0.0
    known_cost_usd: Decimal = Decimal("0")
    unknown_cost_event_ids: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    changes_vs_original: int | None = None

    @property
    def event_ids(self) -> list[str]:
        return [item.event_id for item in self.items]

    def item(self, event_id: str) -> PlanItem | None:
        return next((i for i in self.items if i.event_id == event_id), None)

    def rejection(self, event_id: str) -> Rejection | None:
        return next((r for r in self.rejected if r.event_id == event_id), None)

    def as_decisions(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = [
            {"type": "plan_item", **i.model_dump(mode="json")} for i in self.items
        ]
        out += [{"type": "rejected", **r.model_dump(mode="json")} for r in self.rejected]
        return out
