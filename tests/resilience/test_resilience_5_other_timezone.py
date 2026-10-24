"""(5) In-person event in another timezone: shown with its own zone, kept out of the SF plan."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from conferge.api.app import create_app
from conferge.api.data import load_fixture as load_api_fixture
from conferge.api.providers import Providers
from conferge.core.schemas import Event, SourceEvidence, Venue

SGT = timezone(timedelta(hours=8))
EVENT_ID = "resilience:singapore-meetup"


def _singapore_event(conference_id: str) -> Event:
    # 10:00 in Singapore on Oct 29 is 19:00 in San Francisco on Oct 28: inside the
    # trip and inside waking hours, so only the timezone can exclude it.
    start = datetime(2026, 10, 29, 10, 0, tzinfo=SGT)
    return Event(
        id=EVENT_ID, title="Agentic AI founders breakfast (Singapore)", event_type="side_event",
        conference_id=conference_id, start_at=start, end_at=start + timedelta(hours=2),
        timezone="Asia/Singapore",
        venue=Venue(name="Marina Bay Sands", city="Singapore"),
        source_url="https://example.org/resilience/singapore",
        evidence=[SourceEvidence(provider="resilience-test", source_mode="fixture",
                                 collected_at=datetime(2026, 10, 24, tzinfo=timezone.utc))],
    )


def test_other_timezone_event_is_labelled_and_out_of_the_plan() -> None:
    data = load_api_fixture()
    data.events = [*data.events, _singapore_event(data.conference.id)]
    client = TestClient(create_app(data=data, found=Providers(), graph_probe=False))

    item = next(e for e in client.get("/api/v1/events").json()["items"] if e["id"] == EVENT_ID)
    assert item["timezone"] == "Asia/Singapore"
    assert item["start_at"].endswith("+08:00")  # stored with its own offset, never shifted

    plan = client.get("/api/v1/plan").json()["plan"]
    planned = {i["event_id"] for d in plan["days"] for i in d["items"]}
    assert EVENT_ID not in planned
    reason = next(x for x in plan["excluded"] if x["event_id"] == EVENT_ID)
    assert reason["reason"] == "other_timezone" and "Asia/Singapore" in reason["detail"]

    # Front: times are formatted in the event's own zone and labelled with it.
    js = client.get("/static/app.js").text
    assert re.search(r"timeZone: tz \|\| EVENT_TZ", js)
    assert re.search(r'tz !== EVENT_TZ \? " \(" \+ tz \+ "\)"', js)
    assert re.search(r"fmt(?:Time|Hour)\(\s*(?:event|e)\.start_at,\s*(?:event|e)\.timezone\s*\)", js)
