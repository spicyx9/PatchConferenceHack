"""Deterministic follow-up drafts (no LLM, never sent).

A draft is built only from facts already in the graph path that justified the
meeting: the goal the person serves, the event where they were found, their
company, the shared topic, plus the note the user typed when recording MET.
The note is quoted back to the user for validation, never paraphrased into a
claim about what the contact said. Every draft carries ``sent=False`` and the
list of facts it was built from, so the UI can show "based on" next to it.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from conferge.core.schemas import Company, Conference, Event, Goal, Person

FOLLOW_UP_DELAY_DAYS = 2

NextActionKind = Literal["linkedin_connect", "public_profile_message", "manual"]

_ASK_BY_ROLE = {
    "investor": "I would like to send you a short deck and get your read on it.",
    "founder": "I would be happy to compare notes; would you have 20 minutes next week?",
    "pm": "I would love to show you how we use it day to day and get your feedback.",
    "devrel": "I would be happy to share what we learned building on it.",
    "engineer": "I would be happy to compare notes on the technical side.",
    "executive": "I would like to continue the conversation when you are back.",
}
_GENERIC_ASK = "I would be glad to continue the conversation; would 20 minutes next week work?"


class NextAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: NextActionKind
    label: str
    url: str | None = None
    due_at: datetime


class FollowUpDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    person_id: str
    person_name: str
    subject: str
    message: str
    next_action: NextAction
    based_on: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    status: Literal["draft"] = "draft"
    sent: bool = False


def _first_name(person: Person) -> str:
    return person.name.split(" ")[0]


def _shared_topic(person: Person, goal: Goal | None) -> str | None:
    if goal is None:
        return None
    shared = sorted(set(person.topics) & set(goal.topics))
    return shared[0] if shared else None


def _ask(person: Person, goal: Goal | None) -> str:
    roles = [r for r in person.roles if goal is None or r in goal.target_roles] or list(
        person.roles
    )
    for role in roles:
        if role in _ASK_BY_ROLE:
            return _ASK_BY_ROLE[role]
    return _GENERIC_ASK


def _next_action(person: Person, met_at: datetime) -> NextAction:
    due = met_at + timedelta(days=FOLLOW_UP_DELAY_DAYS)
    if person.linkedin_url:
        return NextAction(
            kind="linkedin_connect",
            label="Connect on LinkedIn with this note",
            url=str(person.linkedin_url),
            due_at=due,
        )
    if person.public_profile_url:
        return NextAction(
            kind="public_profile_message",
            label="Message through the public profile",
            url=str(person.public_profile_url),
            due_at=due,
        )
    return NextAction(
        kind="manual",
        label="No public contact URL: send through your own channel",
        url=None,
        due_at=due,
    )


def draft_followup(
    person: Person,
    *,
    conference: Conference,
    goal: Goal | None,
    event: Event | None = None,
    company: Company | None = None,
    note: str | None = None,
    path_text: str | None = None,
    met_at: datetime | None = None,
) -> FollowUpDraft:
    """Build the draft from the meeting facts. Pure and deterministic."""
    when = met_at or datetime.now(timezone.utc)
    if when.tzinfo is None:
        raise ValueError("met_at must be timezone-aware")
    warnings: list[str] = []
    where = event.title if event is not None else conference.name
    topic = _shared_topic(person, goal)
    note_clean = (note or "").strip()

    lines = [f"Hi {_first_name(person)},", ""]
    opening = f"Good to meet you at {where}"
    if topic:
        opening += f" and to talk about {topic}"
    lines.append(opening + ".")
    if note_clean:
        lines.append(f"[Your note from the meeting, edit before sending: {note_clean}]")
    else:
        warnings.append("no meeting note: the message only uses the graph path")
    if company is not None and goal is not None and goal.target_roles:
        lines.append(
            f"What you are doing at {company.name} is close to why I came to {conference.name}."
        )
    lines.append(_ask(person, goal))
    lines.extend(["", "Best,"])

    if any(e.source_mode == "fixture" for e in person.evidence):
        warnings.append("fixture person: demo draft, not a real contact")
    if goal is None:
        warnings.append("no goal matched: generic ask")

    based_on: dict[str, Any] = {
        "goal": goal.description if goal else None,
        "event": event.title if event else None,
        "company": company.name if company else None,
        "shared_topic": topic,
        "note": note_clean or None,
        "path": path_text or None,
        "met_at": when.isoformat(),
    }
    return FollowUpDraft(
        person_id=person.id,
        person_name=person.name,
        subject=f"Following up from {where}",
        message="\n".join(lines),
        next_action=_next_action(person, when),
        based_on=based_on,
        warnings=warnings,
    )
