import pytest
from people_testkit import evidence, profile
from pydantic import ValidationError

from conferge.people.models import Presence
from conferge.people.taxonomy import (
    extract_topics,
    normalize_roles,
    normalize_topics,
    roles_from_title,
    topics_from_text,
)


def test_topics_keywords_and_boundaries():
    assert topics_from_text("Shipping AI agents over MCP with Copilot") == [
        "ai agents", "mcp", "copilot"]
    assert "developer tools" not in topics_from_text("We provide value")  # no "ide" match
    assert topics_from_text(None, "") == []
    assert "seed investor" not in topics_from_text("seeding a database")


def test_roles_from_title():
    assert roles_from_title("Co-founder & CEO") == ["founder", "executive"]
    assert roles_from_title("Senior Product Manager, Copilot") == ["pm"]
    assert roles_from_title("Tech Lead Venture") == []
    assert roles_from_title(None) == []
    assert normalize_roles(["Seed investors", "PMs", "unknown thing"]) == ["investor", "pm"]


def test_normalize_topics_drops_unknown():
    assert normalize_topics(["AI agents", "Quantum knitting", "MCP"]) == ["ai agents", "mcp"]


@pytest.mark.asyncio
async def test_extract_topics_fallback_and_clipping():
    class Boom:
        async def extract(self, texts):
            raise RuntimeError("no key")

    class Free:
        async def extract(self, texts):
            return ["copilot", "astrology"]

    assert await extract_topics(["AI agents"]) == (["ai agents"], "keywords")
    assert await extract_topics(["AI agents"], Boom()) == (["ai agents"], "keywords_fallback")
    assert await extract_topics(["AI agents"], Free()) == (["ai agents", "copilot"], "llm")


def test_presence_confirmed_only_for_speaker_or_host():
    with pytest.raises(ValidationError):
        Presence(event_id="e", kind="candidate", status="confirmed", evidence=evidence())
    Presence(event_id="e", kind="candidate", status="probable", evidence=evidence())


def test_to_person_never_turns_host_into_speaker():
    p = profile("person:x", "Avery Example", presences=[
        ("ev-talk", "speaker", "confirmed"), ("ev-party", "host", "confirmed")])
    person = p.to_person()
    assert person.participation == "confirmed_speaker"
    assert person.event_ids == ["ev-talk"]
    assert person.presence_confidence == 1.0

    candidate = profile("person:y", "Blake Sample",
                        presences=[("ev-party", "candidate", "probable")]).to_person()
    assert candidate.participation == "relevant_candidate"
    assert candidate.presence_confidence is None
