from datetime import datetime, timezone

import pytest

from conferge.core.schemas import Event, Goal, Person, SourceEvidence, Venue
from conferge.people.models import Presence, PersonProfile

NOW = datetime(2026, 10, 24, 12, 0, tzinfo=timezone.utc)


def evidence(provider: str = "test:fictional", url: str = "https://example.org/e") -> SourceEvidence:
    return SourceEvidence(provider=provider, source_mode="fixture", source_url=url,
                          collected_at=NOW)


def profile(pid: str, name: str, *, title: str | None = None, roles=(), topics=(),
            company_id: str | None = None, company_name: str | None = None,
            presences: list[tuple[str, str, str]] = (), linkedin: str | None = None,
            identity: float | None = None) -> PersonProfile:
    ev = evidence()
    return PersonProfile(
        person=Person(id=pid, name=name, title=title, roles=list(roles), topics=list(topics),
                      company_id=company_id, linkedin_url=linkedin,
                      identity_confidence=identity, evidence=[ev]),
        company_name=company_name,
        presences=[Presence(event_id=e, kind=k, status=s, evidence=ev) for e, k, s in presences],
        merged_from=[pid],
    )


@pytest.fixture
def goals() -> list[Goal]:
    return [
        Goal(id="g-inv", description="Meet seed investors", priority=0.45,
             target_roles=["investor"], topics=["developer tools", "ai agents"]),
        Goal(id="g-fnd", description="Meet AI agent founders", priority=0.35,
             target_roles=["founder"], topics=["ai agents", "mcp"]),
        Goal(id="g-pm", description="Meet Copilot PMs", priority=0.20,
             target_roles=["pm"], topics=["copilot", "mcp"]),
    ]


@pytest.fixture
def events() -> list[Event]:
    return [
        Event(id="ev-talk", title="Agents in production (fictional)", event_type="session",
              start_at=datetime(2026, 10, 28, 10, 30, tzinfo=timezone.utc),
              end_at=datetime(2026, 10, 28, 11, 0, tzinfo=timezone.utc),
              venue=Venue(name="Fort Mason Pavilion"), room="Room A",
              source_url="https://example.org/talk"),
        Event(id="ev-party", title="Example Agents Night (fictional)", event_type="party"),
    ]
