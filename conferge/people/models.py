"""Local adapter models for window 07 (people), built around frozen core schemas.

`core.Person` carries a single `participation` value for all its `event_ids`. A person
can be a speaker at one session and a host of another event, so the per-event presence
is kept here in `Presence` and only projected onto `Person` conservatively
(see `PersonProfile.to_person`). Nothing here is written to the graph directly.
"""

from __future__ import annotations

from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, HttpUrl, model_validator

from conferge.core.schemas import Person, SourceEvidence

PresenceKind = Literal["speaker", "host", "exhibitor", "candidate"]
PresenceStatus = Literal["confirmed", "probable", "unknown"]

# Strength order used to pick the single Person.participation value.
_KIND_TO_PARTICIPATION = {
    "speaker": "confirmed_speaker",
    "host": "confirmed_organizer",
}
_KIND_RANK = {"speaker": 0, "host": 1, "exhibitor": 2, "candidate": 3}


class LocalModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class Presence(LocalModel):
    """One observed link between a person and an event, with its own evidence.

    `confirmed` is only allowed for `speaker` and `host` (published by the organizer).
    Everything else is at most `probable`; we never read private guest lists.
    """

    event_id: str
    kind: PresenceKind
    status: PresenceStatus
    evidence: SourceEvidence

    @model_validator(mode="after")
    def confirmed_only_for_published_roles(self) -> Presence:
        if self.status == "confirmed" and self.kind not in _KIND_TO_PARTICIPATION:
            raise ValueError("only speaker or host presence can be confirmed")
        return self


class PersonProfile(LocalModel):
    """A normalized person plus per-event presences and the company display name."""

    person: Person
    company_name: str | None = None
    presences: list[Presence] = Field(default_factory=list)
    talk_titles: list[str] = Field(default_factory=list)
    merged_from: list[str] = Field(default_factory=list)

    @property
    def id(self) -> str:
        return self.person.id

    @property
    def confirmed(self) -> list[Presence]:
        return [p for p in self.presences if p.status == "confirmed"]

    def to_person(self) -> Person:
        """Project onto core.Person without overstating participation.

        Participation is the strongest confirmed kind; `event_ids` keeps only events
        with that kind, so a graph consumer never turns a host into a speaker.
        """
        confirmed = sorted(self.confirmed, key=lambda p: _KIND_RANK[p.kind])
        if not confirmed:
            return self.person.model_copy(update={
                "participation": "relevant_candidate" if self.presences else "unknown",
                "event_ids": sorted({p.event_id for p in self.presences}),
                "presence_confidence": None,
            })
        kind = confirmed[0].kind
        event_ids = sorted({p.event_id for p in confirmed if p.kind == kind})
        return self.person.model_copy(update={
            "participation": _KIND_TO_PARTICIPATION[kind],
            "event_ids": event_ids,
            "presence_confidence": 1.0,
        })


class ProfileCandidate(LocalModel):
    """One search hit for a person, with the deterministic identity score."""

    url: HttpUrl
    title: str | None = None
    snippet: str | None = None
    score: float = Field(ge=0, le=1)
    reasons: list[str] = Field(default_factory=list)


class ProfileLookup(LocalModel):
    """Result of name + company -> LinkedIn lookup. `linkedin_url` is None below threshold."""

    name: str
    company: str | None = None
    query: str
    linkedin_url: HttpUrl | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    candidates: list[ProfileCandidate] = Field(default_factory=list)
    status: Literal["ok", "degraded", "failed"]
    source_mode: Literal["live", "cached", "fixture"]
    collected_at: AwareDatetime
    error: str | None = None


class WhereSlot(LocalModel):
    """Where a person can be met. Times and venue come from the event, never guessed."""

    event_id: str
    title: str
    kind: PresenceKind
    status: PresenceStatus
    start_at: AwareDatetime | None = None
    end_at: AwareDatetime | None = None
    venue: str | None = None
    room: str | None = None
    source_url: HttpUrl | None = None


class PersonMatch(LocalModel):
    person: Person
    score: float = Field(ge=0, le=100)
    reasons: list[str] = Field(default_factory=list)
    goal_scores: dict[str, float] = Field(default_factory=dict)
    where: list[WhereSlot] = Field(default_factory=list)
    opener: str | None = None
    presence_status: PresenceStatus = "unknown"
    confidence: float | None = Field(default=None, ge=0, le=1)
    scorer: Literal["deterministic", "llm"] = "deterministic"
    warnings: list[str] = Field(default_factory=list)
