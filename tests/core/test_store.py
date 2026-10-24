from unittest.mock import Mock

import pytest

from conferge.core.store import GraphStore


def test_graphstore_parameterized_and_typed():
    graph = Mock()
    store = GraphStore(graph)
    store.merge_node("Event", "e1", {"name": "demo' RETURN n", "source": "luma"})
    query = graph.query.call_args.args[0]
    params = graph.query.call_args.kwargs["params"]
    assert "MERGE (n:Event {id: $id})" in query
    assert "demo' RETURN n" not in query
    assert params["id"] == "e1"
    assert "demo' RETURN n" in params.values()


def test_graphstore_injection_blocked():
    graph = Mock()
    store = GraphStore(graph)
    with pytest.raises(ValueError):
        store.merge_node("Event) DELETE", "e1")
    with pytest.raises(ValueError):
        store.merge_node("Person", "p1", {"name) DELETE n": "evil"})
    with pytest.raises(ValueError):
        store.merge_edge("Person", "p1", "HACK]->", "Event", "e1")
    graph.query.assert_not_called()


def test_edge_uses_parameterized_merge():
    graph = Mock()
    store = GraphStore(graph)
    store.merge_edge("Person", "p1", "SPEAKS_AT", "Event", "e1",
                     {"confidence": 0.85, "source_url": "https://example.com/s1"})
    assert "MERGE (a)-[r:SPEAKS_AT]->(b)" in graph.query.call_args.args[0]
    assert 0.85 in graph.query.call_args.kwargs["params"].values()


def test_edge_gets_rule_rationale_and_evidence_ids():
    graph = Mock()
    GraphStore(graph).merge_edge("Person", "p1", "SPEAKS_AT", "Event", "e1", {
        "source": "rainfocus:github-universe-2026", "source_mode": "live",
        "verification": "event_speaker_list", "source_url": "https://example.com/s1"})
    query, params = graph.query.call_args.args[0], graph.query.call_args.kwargs["params"]
    assert params["evidence_ids"] == ["https://example.com/s1"]
    assert params["rationale"] == ("Listed as speaker of '{to}' on the official GitHub "
                                  "Universe session page")
    # evidence ids are appended on MERGE, never overwritten
    assert "r.evidence_ids + [x IN $evidence_ids WHERE NOT x IN r.evidence_ids]" in query


def test_linkedin_corroboration_rationale_cites_snapshot():
    graph = Mock()
    GraphStore(graph).merge_edge("Person", "p1", "WORKS_AT", "Company", "c1", {
        "linkedin_verification": "linkedin_profile", "linkedin_snapshot_id": "s_abc",
        "linkedin_source_url": "https://www.linkedin.com/in/x",
        "linkedin_observed_at": "2026-10-24T09:00:00+00:00"})
    params = graph.query.call_args.kwargs["params"]
    assert params["evidence_ids"] == ["https://www.linkedin.com/in/x", "s_abc"]
    assert params["rationale"] == ("Works at '{to}': corroborated by LinkedIn profile collected "
                                   "via Bright Data on 2026-10-24")


def test_edge_without_evidence_is_refused():
    graph = Mock()
    with pytest.raises(ValueError, match="no evidence id"):
        GraphStore(graph).merge_edge("Person", "p1", "SPEAKS_AT", "Event", "e1",
                                     {"confidence": 0.85, "source": "luma"})
    graph.query.assert_not_called()


def test_app_records_cite_their_own_id():
    graph = Mock()
    GraphStore(graph).merge_edge("User", "u1", "PLANS", "Event", "e1",
                                 {"state": "invalidated", "invalidated_by": "planner"})
    params = graph.query.call_args.kwargs["params"]
    assert params["evidence_ids"] == ["record:User:u1"]
    assert params["rationale"] == "'{to}' removed from the user's plan by planner"


def test_fixture_rationale_is_labelled():
    graph = Mock()
    GraphStore(graph).merge_edge("Event", "e1", "LOCATED_AT", "Venue", "v1", {
        "source": "luma", "source_mode": "fixture", "source_url": "https://lu.ma/x"})
    assert graph.query.call_args.kwargs["params"]["rationale"] == (
        "[fixture] Venue '{to}' published on the Luma event page")


def test_conference_level_edges_cite_the_official_website():
    graph = Mock()
    GraphStore(graph).merge_edge("Company", "c1", "EXHIBITS_AT", "Conference", "gu", {
        "source": "rainfocus:github-universe-2026", "verification": "sponsor_list",
        "role": "sponsor", "source_url": "https://githubuniverse.com/"})
    assert graph.query.call_args.kwargs["params"]["rationale"] == (
        "Listed as sponsor of '{to}' on the official GitHub Universe website")


def test_rationale_names_both_endpoints_from_the_graph_nodes():
    from conferge.integration.memgraph import MemoryGraph

    graph = MemoryGraph()
    store = GraphStore(graph)
    store.merge_node("Goal", "g1", {"name": "Meet AI agent founders"})
    store.merge_node("Topic", "topic:ai-agents", {"name": "AI agents"})
    store.merge_node("Event", "e1", {"title": "Securing MCP: Real exploits"})
    store.merge_node("Person", "p1", {"name": "Ada"})
    store.merge_edge("Goal", "g1", "ABOUT", "Topic", "topic:ai-agents",
                     {"verification": "user_goal", "source": "user"})
    store.merge_edge("Event", "e1", "ABOUT", "Topic", "topic:ai-agents",
                     {"verification": "event_record", "source": "luma", "source_url": "https://lu.ma/x"})
    store.merge_edge("Person", "p1", "SPEAKS_AT", "Event", "e1",
                     {"verification": "event_speaker_list", "source": "luma",
                      "source_url": "https://lu.ma/x"})
    rationale = {key[2] + ":" + key[1]: props["rationale"] for key, props in graph.edges.items()}
    assert rationale == {
        "ABOUT:g1": "Topic 'AI agents' stated by the user in goal 'Meet AI agent founders'",
        "ABOUT:e1": "Session tagged 'AI agents' on the Luma event page",
        "SPEAKS_AT:p1": "Listed as speaker of 'Securing MCP: Real exploits' on the Luma event page",
    }
