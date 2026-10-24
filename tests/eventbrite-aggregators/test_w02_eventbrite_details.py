"""EventbriteSource.fetch_details: JSON-LD extraction and visible failures."""

from __future__ import annotations

import httpx
import pytest

from conferge.core.schemas import SourceRef
from conferge.events.eventbrite.source import EventbriteSource, SearchFailure, extract_jsonld

_PAGE = (
    '<html><head><script type="application/ld+json">{"@type": "Organization"}</script>'
    '<script type="application/ld+json">{"@type": "SocialEvent", "name": "AI Night",'
    ' "startDate": "2026-10-28T18:00:00-07:00"}</script></head></html>'
)


def _source(status: int, body: str) -> EventbriteSource:
    transport = httpx.MockTransport(lambda request: httpx.Response(status, text=body))
    client = httpx.AsyncClient(transport=transport, base_url="https://www.eventbrite.com")
    return EventbriteSource(client=client, request_delay=0)


def test_extract_jsonld_skips_invalid_blocks() -> None:
    html = _PAGE + '<script type="application/ld+json">{not json</script>'
    assert [b["@type"] for b in extract_jsonld(html)] == ["Organization", "SocialEvent"]


async def test_fetch_details_keeps_event_jsonld() -> None:
    ref = SourceRef(provider="eventbrite", source_id="123", url="https://www.eventbrite.com/e/x-123")
    record = await _source(200, _PAGE).fetch_details(ref)
    assert record.source_mode == "live"
    assert record.payload["jsonld"]["name"] == "AI Night"
    assert str(record.source_url) == "https://www.eventbrite.com/e/x-123"


async def test_fetch_details_without_event_block_is_schema_changed() -> None:
    ref = SourceRef(provider="eventbrite", source_id="123")
    with pytest.raises(SearchFailure) as info:
        await _source(200, "<html></html>").fetch_details(ref)
    assert info.value.termination == "schema_changed"


async def test_fetch_details_403_is_blocked() -> None:
    ref = SourceRef(provider="eventbrite", source_id="123")
    with pytest.raises(SearchFailure) as info:
        await _source(403, "denied").fetch_details(ref)
    assert info.value.termination == "blocked"
