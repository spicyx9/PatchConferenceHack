"""Stable v0.2 data contracts for every Conferge workstream.

All source records preserve provenance; missing details are represented by None,
never invented. No modules outside window 0 should edit this file.

v0.2: optional fields added for topics, registration counts, price breakdown,
person enrichment, baggage and graph paths. All additions are optional with
defaults, so v0.1 payloads remain valid.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Annotated, Any, Generic, Literal, TypeVar

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, HttpUrl, StringConstraints, field_validator, model_validator

DataMode = Literal["live", "cached", "fixture", "mixed"]
SourceMode = Literal["live", "cached", "fixture"]
RunStatus = Literal["ok", "degraded", "failed"]
Termination = Literal[
    "exhausted", "not_applicable", "cursor_stuck", "page_cap", "rate_limited",
    "blocked", "schema_changed", "error",
]
MoneyString = Annotated[str, StringConstraints(pattern=r"^[0-9]+(?:\.[0-9]{1,4})?$")]
T = TypeVar("T")


class CoreModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class SourceEvidence(CoreModel):
    provider: str
    source_mode: SourceMode
    source_url: HttpUrl | None = None
    collected_at: AwareDatetime | None = None
    raw_ref: str | None = None
    source_record_id: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)


class SourceRef(CoreModel):
    provider: str
    source_id: str
    url: HttpUrl | None = None


class SourceRecord(CoreModel):
    provider: str
    source_id: str
    source_mode: SourceMode
    collected_at: AwareDatetime
    payload: dict[str, Any] = Field(default_factory=dict)
    source_url: HttpUrl | None = None
    request_id: str | None = None
    content_hash: str | None = None

    def as_ref(self) -> SourceRef:
        return SourceRef(provider=self.provider, source_id=self.source_id, url=self.source_url)


class RunReport(CoreModel):
    provider: str
    started_at: AwareDatetime
    finished_at: AwareDatetime
    status: RunStatus
    termination: Termination
    source_mode: SourceMode
    fetched_count: int = Field(ge=0)
    unique_count: int = Field(ge=0)
    pages: int = Field(default=0, ge=0)
    expected_count: int | None = Field(default=None, ge=0)
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def check_run(self) -> RunReport:
        if self.finished_at < self.started_at:
            raise ValueError("finished_at must not precede started_at")
        if self.unique_count > self.fetched_count:
            raise ValueError("unique_count cannot exceed fetched_count")
        if self.status == "ok" and self.termination not in {"exhausted", "not_applicable"}:
            raise ValueError("incomplete termination cannot be reported as ok")
        return self


class DiscoveryQuery(CoreModel):
    domain: Literal["events", "conference", "people", "lodging", "flights"]
    conference_id: str | None = None
    city: str | None = None
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    radius_km: float | None = Field(default=None, ge=0)
    start_date: date | None = None
    end_date: date | None = None
    keywords: list[str] = Field(default_factory=list)
    limit: int = Field(default=50, ge=1, le=1000)
    filters: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def valid_dates(self) -> DiscoveryQuery:
        if self.start_date and self.end_date and self.start_date > self.end_date:
            raise ValueError("start_date must be <= end_date")
        return self


class DiscoveryResult(CoreModel):
    items: list[SourceRecord] = Field(default_factory=list)
    run_report: RunReport
    errors: list[str] = Field(default_factory=list)

    @property
    def source_mode(self) -> SourceMode:
        return self.run_report.source_mode


class DataEnvelope(CoreModel, Generic[T]):
    items: list[T] = Field(default_factory=list)
    source_mode: DataMode
    status: RunStatus
    collected_at: AwareDatetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    reports: list[RunReport] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class Conference(CoreModel):
    id: str
    name: str
    start_date: date
    end_date: date
    city: str
    venue_name: str | None = None
    timezone: str
    official_url: HttpUrl | None = None
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    topics: list[str] = Field(default_factory=list)
    sponsor_ids: list[str] = Field(default_factory=list)
    evidence: list[SourceEvidence] = Field(default_factory=list)


class Venue(CoreModel):
    name: str | None = None
    address: str | None = None
    city: str | None = None
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    coordinate_precision: Literal["exact", "approximate", "city", "unknown"] = "unknown"


class Event(CoreModel):
    id: str
    conference_id: str | None = None
    title: str
    description: str | None = None
    event_type: Literal["conference", "session", "side_event", "meetup", "party", "workshop", "other"] = "other"
    start_at: AwareDatetime | None = None
    end_at: AwareDatetime | None = None
    timezone: str | None = None
    venue: Venue | None = None
    organizer_ids: list[str] = Field(default_factory=list)
    organizer_names: list[str] = Field(default_factory=list)
    speaker_ids: list[str] = Field(default_factory=list)
    topics: list[str] = Field(default_factory=list)
    room: str | None = None
    status: Literal["scheduled", "cancelled", "postponed", "sold_out", "unknown"] = "unknown"
    conference_relation: Literal["official", "confirmed_side_event", "candidate", "unrelated", "unknown"] = "unknown"
    relation_score: float | None = Field(default=None, ge=0, le=1)
    relation_evidence: list[str] = Field(default_factory=list)
    registration_url: HttpUrl | None = None
    source_url: HttpUrl | None = None
    is_free: bool | None = None
    price_min: MoneyString | None = None
    price_max: MoneyString | None = None
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    capacity: int | None = Field(default=None, ge=0)
    registered_count: int | None = Field(default=None, ge=0)
    first_listed_at: AwareDatetime | None = None
    evidence: list[SourceEvidence] = Field(default_factory=list)

    @model_validator(mode="after")
    def valid_times(self) -> Event:
        if self.start_at and self.end_at and self.end_at < self.start_at:
            raise ValueError("Event end_at must be >= start_at")
        if self.conference_relation in {"official", "confirmed_side_event"} and not self.relation_evidence:
            raise ValueError("confirmed conference relation requires evidence")
        return self


class Person(CoreModel):
    id: str
    name: str
    company_id: str | None = None
    role: str | None = None
    title: str | None = None
    public_profile_url: HttpUrl | None = None
    linkedin_url: HttpUrl | None = None
    github_url: HttpUrl | None = None
    x_handle: str | None = None
    bio: str | None = None
    topics: list[str] = Field(default_factory=list)
    roles: list[Literal["founder", "investor", "pm", "engineer", "devrel", "executive", "other"]] = Field(default_factory=list)
    participation: Literal[
        "confirmed_speaker", "confirmed_organizer", "public_attendee_listing",
        "relevant_candidate", "unknown",
    ] = "unknown"
    event_ids: list[str] = Field(default_factory=list)
    match_confidence: float | None = Field(default=None, ge=0, le=1)
    identity_confidence: float | None = Field(default=None, ge=0, le=1)
    """Confidence (0-1) that the linked profiles really belong to this person."""
    presence_confidence: float | None = Field(default=None, ge=0, le=1)
    """Confidence (0-1) that this person is linked to the event."""
    evidence: list[SourceEvidence] = Field(default_factory=list)


class Company(CoreModel):
    id: str
    name: str
    domain: str | None = None
    linkedin_url: HttpUrl | None = None
    industry: str | None = None
    is_investor: bool | None = None
    categories: list[str] = Field(default_factory=list)
    evidence: list[SourceEvidence] = Field(default_factory=list)


class Lodging(CoreModel):
    id: str
    name: str
    provider: str
    lodging_type: Literal["hotel", "apartment", "hostel", "other"] = "other"
    check_in: date
    check_out: date
    adults: int = Field(ge=1)
    rooms: int = Field(default=1, ge=1)
    venue: Venue | None = None
    distance_to_venue_m: int | None = Field(default=None, ge=0)
    total_price: Decimal | None = Field(default=None, ge=0)
    nightly_avg: Decimal | None = Field(default=None, ge=0)
    base_total: Decimal | None = Field(default=None, ge=0)
    taxes: Decimal | None = Field(default=None, ge=0)
    fees_total: Decimal | None = Field(default=None, ge=0)
    payable_at_property: Decimal | None = Field(default=None, ge=0)
    currency: str | None = None
    price_status: Literal["verified_bookable", "quoted_total", "indicative", "unavailable", "unknown"] = "unknown"
    availability: Literal["verified_available", "unavailable", "unknown"] = "unknown"
    verified_at: AwareDatetime | None = None
    includes_all_fees: bool | None = None
    free_cancellation: bool | None = None
    rating: float | None = Field(default=None, ge=0)
    rating_scale: int | None = Field(default=None, ge=1)
    rating_count: int | None = Field(default=None, ge=0)
    booking_url: HttpUrl | None = None
    dedup_group: str | None = None
    evidence: list[SourceEvidence] = Field(default_factory=list)

    @model_validator(mode="after")
    def price_and_dates(self) -> Lodging:
        if self.check_out <= self.check_in:
            raise ValueError("check_out must follow check_in")
        if self.price_status == "verified_bookable":
            if self.availability != "verified_available" or self.total_price is None or not self.booking_url:
                raise ValueError("verified_bookable needs verified availability, total price and link")
        return self


class FlightSegment(CoreModel):
    origin_iata: str = Field(pattern=r"^[A-Z]{3}$")
    destination_iata: str = Field(pattern=r"^[A-Z]{3}$")
    departure_at: AwareDatetime | None = None
    arrival_at: AwareDatetime | None = None
    marketing_carrier: str | None = None
    operating_carrier: str | None = None
    flight_number: str | None = None
    aircraft: str | None = None
    duration_minutes: int | None = Field(default=None, ge=0)
    connection_type: Literal["managed", "self_transfer", "protected_self_transfer", "unknown"] = "unknown"


class FlightSlice(CoreModel):
    segments: list[FlightSegment] = Field(min_length=1)
    duration_minutes: int | None = Field(default=None, ge=0)
    self_transfer: bool | None = None

    @property
    def stops(self) -> int:
        return max(len(self.segments) - 1, 0)


class FlightOffer(CoreModel):
    id: str
    dedup_key: str | None = None
    trip_type: Literal["one_way", "round_trip", "multi_city"]
    slices: list[FlightSlice] = Field(min_length=1)
    total_price: MoneyString | None = None
    raw_price_text: str | None = None
    price_scope: Literal["total_all_passengers", "per_adult", "unknown"] = "unknown"
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    price_status: Literal["observed_live", "cached", "revalidated", "sandbox", "unknown"] = "unknown"
    collected_at: AwareDatetime
    booking_url: HttpUrl | None = None
    booking_url_type: Literal["google_flights_booking", "google_flights_search", "seller_deeplink", "airline", "unknown"] = "unknown"
    baggage_verified: bool | None = None
    carry_on_included: bool | None = None
    checked_bags_included: int | None = Field(default=None, ge=0)
    warnings: list[str] = Field(default_factory=list)
    evidence: list[SourceEvidence] = Field(default_factory=list)

    @field_validator("total_price")
    @classmethod
    def parse_money_string(cls, value: str | None) -> str | None:
        if value is not None:
            try:
                if not Decimal(value).is_finite() or Decimal(value) < 0:
                    raise ValueError("price must be a finite nonnegative decimal string")
            except InvalidOperation as exc:
                raise ValueError("invalid price decimal") from exc
        return value

    @model_validator(mode="after")
    def validate_offer(self) -> FlightOffer:
        if self.price_status != "unknown" and self.total_price is None:
            raise ValueError("price_status requires an actual price")
        if self.total_price is not None and self.currency is None:
            raise ValueError("currency required when price exists")
        if self.trip_type == "round_trip" and len(self.slices) != 2:
            raise ValueError("round_trip must have exactly 2 slices")
        return self


class Goal(CoreModel):
    id: str
    description: str
    priority: float = Field(default=1.0, ge=0, le=1)
    tags: list[str] = Field(default_factory=list)
    topics: list[str] = Field(default_factory=list)
    target_roles: list[str] = Field(default_factory=list)
    target_count: int | None = Field(default=None, ge=0)
    stated_at: AwareDatetime | None = None
    """When the user stated this goal (POST /goal); None for configured demo goals."""


class Opportunity(CoreModel):
    id: str
    title: str
    goal_ids: list[str]
    event_id: str | None = None
    person_ids: list[str] = Field(default_factory=list)
    company_ids: list[str] = Field(default_factory=list)
    score: float = Field(ge=0, le=100)
    rationale: str
    path: list[dict[str, Any]] = Field(default_factory=list)
    where: str | None = None
    opener: str | None = None
    presence: Literal["confirmed", "probable", "unknown"] = "unknown"
    evidence: list[SourceEvidence] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class AgentContext(CoreModel):
    conference: Conference
    goals: list[Goal]
    data_mode: DataMode = "fixture"
    user_id: str = "demo-user"
    events: list[Event] = Field(default_factory=list)
    people: list[Person] = Field(default_factory=list)
    opportunities: list[Opportunity] = Field(default_factory=list)
    budget_usd: Decimal | None = Field(default=None, ge=0)
    constraints: dict[str, Any] = Field(default_factory=dict)


class AgentResult(CoreModel):
    agent: str
    source_mode: DataMode
    status: RunStatus
    opportunities: list[Opportunity] = Field(default_factory=list)
    decisions: list[dict[str, Any]] = Field(default_factory=list)
    explanations: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
