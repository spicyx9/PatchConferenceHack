"""Offline ingestion tests: GraphStore(Mock()) records every Cypher write."""

from __future__ import annotations

import re
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any
from unittest.mock import Mock

import pytest

from conferge.core.schemas import (
    Event,
    FlightOffer,
    FlightSegment,
    FlightSlice,
    Lodging,
    Person,
    SourceEvidence,
)
from conferge.core.store import GraphStore
from conferge.graph.bundle import GraphBundle, ingest_bundle
from conferge.graph.ingest import GraphIngestor
from conferge.graph.memory import record_memory
from conferge.graph.schema import venue_id
from conferge.graph.seed import load_graph_fixture
from conferge.graph.textgraph import extract_topics, link_text_topics, similar_topics

NODE_RE = re.compile(
    r"^MERGE \(n:[A-Za-z]+ \{id: \$id\}\)"
    r"(?: SET n\.\w+ = \$prop_\d+(?:, n\.\w+ = \$prop_\d+)*)? RETURN n\.id$"
)
EDGE_RE = re.compile(
    r"^MATCH \(a:[A-Za-z]+ \{id: \$from_id\}\), \(b:[A-Za-z]+ \{id: \$to_id\}\) "
    r"MERGE \(a\)-\[r:[A-Z_]+\]->\(b\)"
    r"(?: SET r\.\w+ = \$prop_\d+(?:, r\.\w+ = \$prop_\d+)*)? RETURN a\.id, b\.id$"
)
ASSIGN_RE = re.compile(r"[nr]\.(\w+) = \$(prop_\d+)")
NODE_HEAD_RE = re.compile(r"^MERGE \(n:(\w+) ")
EDGE_HEAD_RE = re.compile(r"^MATCH \(a:(\w+) .*?\(b:(\w+) .*?MERGE \(a\)-\[r:(\w+)\]")

AT = datetime(2026, 10, 23, 12, 0, tzinfo=timezone.utc)


def _decode(call: Any) -> dict[str, Any]:
    cypher = call.args[0]
    params = call.kwargs["params"]
    props = {key: params[name] for key, name in ASSIGN_RE.findall(cypher)}
    if cypher.startswith("MERGE (n:"):
        return {"type": "node", "label": NODE_HEAD_RE.match(cypher).group(1),
                "id": params["id"], "props": props, "cypher": cypher, "params": params}
    from_kind, to_kind, rel = EDGE_HEAD_RE.match(cypher).groups()
    return {"type": "edge", "from_kind": from_kind, "to_kind": to_kind, "rel": rel,
            "from": params["from_id"], "to": params["to_id"], "props": props,
            "cypher": cypher, "params": params}


def _writes(graph: Mock) -> list[dict[str, Any]]:
    return [_decode(c) for c in graph.query.call_args_list]


def _nodes(writes: list[dict[str, Any]], label: str | None = None) -> list[dict[str, Any]]:
    return [w for w in writes if w["type"] == "node" and (label is None or w["label"] == label)]


def _edges(writes: list[dict[str, Any]], rel: str | None = None) -> list[dict[str, Any]]:
    return [w for w in writes if w["type"] == "edge" and (rel is None or w["rel"] == rel)]


def _ingest(bundle: GraphBundle, **kwargs: Any) -> tuple[Mock, Any, list[dict[str, Any]]]:
    graph = Mock()
    report = ingest_bundle(GraphStore(graph), bundle, **kwargs)
    return graph, report, _writes(graph)


@pytest.fixture(scope="module")
def bundle() -> GraphBundle:
    return load_graph_fixture()


@pytest.fixture(scope="module")
def ingested(bundle: GraphBundle) -> tuple[Mock, Any, list[dict[str, Any]]]:
    return _ingest(bundle)


def _fx_evidence(url: str | None = None) -> list[SourceEvidence]:
    return [SourceEvidence(provider="test", source_mode="fixture", collected_at=AT,
                           source_url=url)]


# -- write shapes ----------------------------------------------------------------


def test_only_graphstore_merge_shapes_all_values_parameterized(ingested):
    graph, _, writes = ingested
    assert graph.query.call_count > 0
    for call in graph.query.call_args_list:
        cypher = call.args[0]
        assert cypher.startswith("MERGE (n:") or (
            cypher.startswith("MATCH (a:") and "MERGE (a)-[r:" in cypher)
        # Full-grammar match proves no literal value is interpolated into Cypher.
        assert NODE_RE.fullmatch(cypher) or EDGE_RE.fullmatch(cypher), cypher
        assert set(call.kwargs) == {"params"}
    assert writes


def test_provenance_on_every_node_and_edge(ingested):
    _, _, writes = ingested
    for node in _nodes(writes):
        assert "source_mode" in node["props"], node
        assert "ingested_at" in node["props"], node
    for edge in _edges(writes):
        assert "verification" in edge["props"], edge
        assert "source_mode" in edge["props"], edge


def test_fixture_bundle_stays_fixture_mode(ingested):
    _, _, writes = ingested
    modes = {w["props"]["source_mode"] for w in writes}
    assert modes == {"fixture"}


# -- attendance / participation ---------------------------------------------------


def test_attends_confirmed_requires_evidence_url(ingested):
    _, report, writes = ingested
    attends = _edges(writes, "ATTENDS_CONFIRMED")
    assert {(e["from"], e["to"]) for e in attends} == {("p-fx-carol", "e-fx-agents-night")}
    assert attends[0]["props"]["evidence_url"] == "https://example.org/fixture/agents-night/guests"
    assert any("p-fx-gina" in s and "ATTENDS_CONFIRMED" in s for s in report.skipped_edges)


def test_relevant_candidates_get_no_participation_edges(bundle, ingested):
    _, _, writes = ingested
    candidates = {p.id for p in bundle.people if p.participation == "relevant_candidate"}
    assert candidates  # fixture contains bob and frank
    for edge in _edges(writes):
        if edge["rel"] in {"ATTENDS_CONFIRMED", "SPEAKS_AT"}:
            assert edge["from"] not in candidates


def test_relevant_candidate_with_event_and_url_still_no_attendance(bundle):
    person = Person(id="p-cand", name="Fixture Candidate", participation="relevant_candidate",
                    event_ids=["e-fx-agents-night"],
                    evidence=_fx_evidence("https://example.org/fixture/x"))
    variant = bundle.model_copy(update={"people": [*bundle.people, person]})
    _, _, writes = _ingest(variant)
    rels = {e["rel"] for e in _edges(writes) if e["from"] == "p-cand"}
    assert not rels & {"ATTENDS_CONFIRMED", "SPEAKS_AT", "HOSTS"}


# -- None handling ----------------------------------------------------------------


def test_none_fields_not_sent(ingested):
    _, _, writes = ingested
    untimed = [n for n in _nodes(writes, "Event") if n["id"] == "e-fx-oss-breakfast"]
    assert len(untimed) == 1
    props = untimed[0]["props"]
    for key in ("start_at", "end_at", "start_ts", "end_ts", "description", "price_min",
                "timezone"):
        assert key not in props
    assert None not in untimed[0]["params"].values()
    for write in writes:
        assert None not in write["params"].values(), write
    timed = next(n for n in _nodes(writes, "Event") if n["id"] == "e-fx-talk-agents")
    assert timed["props"]["start_at"] == "2026-10-28T14:00:00-07:00"
    assert isinstance(timed["props"]["start_ts"], int)


# -- dedup / corroboration --------------------------------------------------------


def test_duplicate_edges_written_once_first_verification_kept(ingested):
    _, report, writes = ingested
    speaks = [e for e in _edges(writes, "SPEAKS_AT")
              if (e["from"], e["to"]) == ("p-fx-alice", "e-fx-talk-agents")]
    assert len(speaks) == 1
    assert speaks[0]["props"]["verification"] == "event_speaker_list"
    assert report.corroborated_edges >= 1
    keys = [(e["from"], e["rel"], e["to"]) for e in _edges(writes)]
    assert len(keys) == len(set(keys))


# -- PART_OF ------------------------------------------------------------------------


def test_part_of_carries_relation(bundle, ingested):
    _, _, writes = ingested
    part_of = {e["from"]: e for e in _edges(writes, "PART_OF")}
    for event in bundle.events:
        assert part_of[event.id]["props"]["relation"] == event.conference_relation
        assert part_of[event.id]["to"] == bundle.conference.id
    assert part_of["e-fx-devtools-mixer"]["props"]["verification"] == "unverified"
    assert part_of["e-fx-talk-agents"]["props"]["verification"] == "relation_evidence"


def test_unrelated_event_gets_no_part_of(bundle):
    event = Event(id="e-unrelated", conference_id=bundle.conference.id,
                  title="[FIXTURE] Unrelated", conference_relation="unrelated",
                  evidence=_fx_evidence())
    variant = bundle.model_copy(update={"events": [*bundle.events, event]})
    _, _, writes = _ingest(variant)
    assert any(n["id"] == "e-unrelated" for n in _nodes(writes, "Event"))
    assert not [e for e in _edges(writes, "PART_OF") if e["from"] == "e-unrelated"]


# -- unknown references ---------------------------------------------------------------


def test_unknown_organizer_and_speaker_skipped(bundle):
    event = Event(id="e-ghost", conference_id=bundle.conference.id, title="[FIXTURE] Ghost",
                  speaker_ids=["p-unknown"], organizer_ids=["c-unknown"],
                  evidence=_fx_evidence())
    variant = bundle.model_copy(update={"events": [*bundle.events, event]})
    _, report, writes = _ingest(variant)
    ids = {w.get("id") for w in writes} | {e["from"] for e in _edges(writes)} | {
        e["to"] for e in _edges(writes)}
    assert "p-unknown" not in ids
    assert "c-unknown" not in ids
    assert any("p-unknown" in s and "SPEAKS_AT" in s for s in report.skipped_edges)
    assert any("c-unknown" in s and "HOSTS" in s for s in report.skipped_edges)


def test_platform_organizers_become_host_nodes_with_listed_names(bundle):
    event = Event(id="e-luma", conference_id=bundle.conference.id, title="[FIXTURE] Luma",
                  organizer_ids=["luma:host:usr-1", "luma:calendar:cal-1"],
                  organizer_names=["Ada Host", "Agents Club"], evidence=_fx_evidence())
    unaligned = Event(id="e-eb", conference_id=bundle.conference.id, title="[FIXTURE] EB",
                      organizer_ids=["eventbrite-organizer:9"], organizer_names=[],
                      evidence=_fx_evidence())
    variant = bundle.model_copy(update={"events": [*bundle.events, event, unaligned]})
    _, report, writes = _ingest(variant)
    people = {n["id"]: n for n in _nodes(writes, "Person")}
    companies = {n["id"]: n for n in _nodes(writes, "Company")}
    assert people["luma:host:usr-1"]["props"]["name"] == "Ada Host"
    assert people["luma:host:usr-1"]["props"]["participation"] == "confirmed_organizer"
    assert companies["luma:calendar:cal-1"]["props"]["name"] == "Agents Club"
    hosts = {(e["from"], e["to"]) for e in _edges(writes, "HOSTS")}
    assert {("luma:host:usr-1", "e-luma"), ("luma:calendar:cal-1", "e-luma")} <= hosts
    # No listed name to pair with: no node is invented, the edge stays reported.
    assert "eventbrite-organizer:9" not in companies
    assert any("eventbrite-organizer:9" in s and "HOSTS" in s for s in report.skipped_edges)


# -- memory -----------------------------------------------------------------------------


def test_record_memory_met_writes_meeting_and_met_edge():
    graph = Mock()
    node_id = record_memory(GraphStore(graph), "demo-user", "MET", "Person", "p-fx-alice",
                            note="coffee", at=AT)
    writes = _writes(graph)
    assert [w["type"] for w in writes] == ["node", "edge"]
    assert writes[0]["label"] == "Meeting" and writes[0]["id"] == node_id
    assert writes[0]["props"]["kind"] == "MET"
    assert writes[0]["props"]["at"] == AT.isoformat()
    edge = writes[1]
    assert (edge["rel"], edge["from_kind"], edge["to_kind"], edge["to"]) == (
        "MET", "Meeting", "Person", "p-fx-alice")
    assert edge["props"]["verification"] == "user_reported"


def test_record_memory_contacted_uses_involves():
    graph = Mock()
    record_memory(GraphStore(graph), "demo-user", "CONTACTED", "Person", "p-fx-carol", at=AT)
    edge = _edges(_writes(graph))[0]
    assert edge["rel"] == "INVOLVES"


def test_record_memory_rejects_naive_and_met_non_person():
    graph = Mock()
    store = GraphStore(graph)
    with pytest.raises(ValueError):
        record_memory(store, "demo-user", "MET", "Person", "p1", at=datetime(2026, 10, 28, 9))
    with pytest.raises(ValueError):
        record_memory(store, "demo-user", "MET", "Event", "e1", at=AT)
    graph.query.assert_not_called()


# -- lodging / flights ---------------------------------------------------------------------


def _lodging(lid: str, distance: int | None) -> Lodging:
    return Lodging(id=lid, name=f"Fixture Hotel {lid}", provider="test",
                   check_in=date(2026, 10, 27), check_out=date(2026, 10, 30), adults=1,
                   distance_to_venue_m=distance, total_price=Decimal("245.50"),
                   currency="USD", price_status="quoted_total", evidence=_fx_evidence())


def test_lodging_near_only_with_distance(bundle):
    variant = bundle.model_copy(update={"lodging": [_lodging("l-near", 800),
                                                    _lodging("l-far", None)]})
    _, _, writes = _ingest(variant)
    near = _edges(writes, "NEAR")
    vid = venue_id(bundle.conference.venue_name, None, bundle.conference.city)
    assert [(e["from"], e["to"]) for e in near] == [("l-near", vid)]
    assert near[0]["props"]["distance_m"] == 800
    lodging = {n["id"]: n for n in _nodes(writes, "Lodging")}
    assert set(lodging) == {"l-near", "l-far"}
    assert lodging["l-near"]["props"]["total_price"] == "245.50"
    assert isinstance(lodging["l-near"]["props"]["total_price"], str)


def test_flight_offer_node_price_string_and_collected_at():
    offer = FlightOffer(
        id="f-1", trip_type="one_way",
        slices=[FlightSlice(segments=[FlightSegment(origin_iata="JFK", destination_iata="SFO")])],
        total_price="312.40", currency="USD", price_status="observed_live", collected_at=AT,
        evidence=_fx_evidence())
    graph = Mock()
    ing = GraphIngestor(GraphStore(graph), default_mode="fixture")
    ing.ingest_flights([offer])
    node = _nodes(_writes(graph), "FlightOffer")[0]
    assert node["props"]["total_price"] == "312.40"
    assert node["props"]["collected_at"] == AT.isoformat()
    assert node["props"]["origin_iata"] == "JFK"
    assert node["props"]["destination_iata"] == "SFO"


# -- textgraph ------------------------------------------------------------------------------


def test_extract_topics_aliases_and_word_boundaries():
    assert "AI agents" in extract_topics("building agentic tools")
    assert "MCP" in extract_topics("Speaks about the Model Context Protocol")
    assert "venture capital" not in extract_topics("the avcx hackathon")
    assert "venture capital" in extract_topics("a VC from a seed fund")
    assert extract_topics(None) == []
    assert extract_topics("") == []


def test_link_text_topics_skips_declared():
    graph = Mock()
    ing = GraphIngestor(GraphStore(graph), default_mode="fixture")
    found = link_text_topics(ing, "Person", "p1", "agentic founder using MCP",
                             _fx_evidence(), declared=["AI agents"])
    assert found == ["MCP"]
    about = _edges(_writes(graph), "ABOUT")
    assert [(e["from"], e["to"]) for e in about] == [("p1", "topic:mcp")]
    assert about[0]["props"]["verification"] == "keyword_match"
    assert about[0]["props"]["kind"] == "text"


def test_similar_topics_ordering():
    result = similar_topics("ai agents tools", ["AI agents", "developer tools", "MCP", "agents"])
    names = [name for name, _ in result]
    assert "MCP" not in names
    assert names[0] == "AI agents"
    scores = [score for _, score in result]
    assert scores == sorted(scores, reverse=True)
    # ties are broken alphabetically
    tied = similar_topics("x y", ["y", "x"])
    assert [n for n, _ in tied] == ["x", "y"]
    assert similar_topics("a b c", ["a", "b", "c"], k=2) == [("a", 0.3333), ("b", 0.3333)]
