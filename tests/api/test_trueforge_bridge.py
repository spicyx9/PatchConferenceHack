"""The agent cannot return identities outside the caller's filtered directory."""
import json

import pytest

from conferge.api.trueforge import parse_trace


def trace(items):
    return [
        {"type": "model.message.delta", "tool_calls": [{"id": "c1", "function": {"name": "search_connections"}}]},
        {"type": "tool.response", "tool_call_id": "c1", "content": json.dumps({"mode": "semantic", "items": items})},
        {"type": "turn.done", "state": {"status": "done", "output": {"content": "Matches"}}},
    ]


def test_agent_results_use_canonical_profiles_and_respect_filters():
    result = parse_trace(trace([
        {"id": "allowed", "name": "Invented name", "reason": "Relevant"},
        {"id": "outside-filter", "name": "Other"},
        {"id": "fabricated"},
    ]), {"allowed": {"id": "allowed", "name": "Real name", "photo": {"url": "/photo"}}})
    assert result["items"] == [{"id": "allowed", "name": "Real name", "photo": {"url": "/photo"}, "reason": "Relevant"}]
    assert result["agent_runtime"] == "trueforge"


def test_model_answer_without_tool_evidence_is_rejected():
    with pytest.raises(ValueError, match="grounded search"):
        parse_trace([{"type": "turn.done", "state": {"status": "done", "output": {"content": "Invented"}}}], {})


def test_empty_search_is_valid_but_tool_error_is_not():
    assert parse_trace(trace([]), {})["items"] == []
    events = trace([])
    events[1]["content"] = "Provider failed"
    with pytest.raises(ValueError, match="grounded search"):
        parse_trace(events, {})


def test_failed_agent_turn_does_not_silently_fall_back():
    events = trace([])
    events[-1]["state"]["status"] = "failed"
    with pytest.raises(ValueError, match="grounded search"):
        parse_trace(events, {})
