"""Every edge of the loaded demo graph carries a rationale and at least one evidence id."""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone

import pytest

from conferge.api.logic import parse_goals
from conferge.core.store import GraphStore
from conferge.graph import GraphBundle, ingest_bundle
from conferge.integration import pipeline
from conferge.integration.assemble import assemble
from conferge.integration.memgraph import MemoryGraph


def _demo_bundle() -> GraphBundle:
    """The bundle scripts/run_demo.py loads in fixture mode (no travel, no LinkedIn)."""
    slices = asyncio.run(pipeline._collect("fixture", False, 90.0, None))
    assembly = assemble(pipeline._usable(slices), None)
    goals = parse_goals(assembly.demo.demo_goal_text)
    opps = asyncio.run(pipeline._stage_planning(
        pipeline.E2EReport(mode="fixture", started_at=datetime.now(timezone.utc)), assembly, goals))
    return GraphBundle(
        source_mode="fixture", note="tests/graph/test_edge_rationale.py",
        conference=assembly.conference, companies=assembly.companies,
        people=assembly.people, events=assembly.events, goals=goals,
        opportunities=[o for o in opps if set(o.goal_ids) <= {g.id for g in goals}],
        lodging=assembly.demo.stays, flights=assembly.demo.flights,
    )


@pytest.fixture(scope="module")
def loaded() -> tuple[MemoryGraph, object]:
    graph = MemoryGraph()
    report = ingest_bundle(GraphStore(graph), _demo_bundle())
    return graph, report


def test_no_edge_without_evidence_id_in_the_demo_graph(loaded):
    graph, report = loaded
    assert sum(graph.count_edges().values()) > 1000
    assert graph.edges_missing("evidence_ids") == []
    assert graph.edges_missing("rationale") == []
    assert not [s for s in report.skipped_edges if "no evidence id" in s]


def test_demo_rationales_name_their_entities(loaded):
    graph, _ = loaded
    speaks = [(key, p) for key, p in graph.edges.items() if key[2] == "SPEAKS_AT"]
    assert speaks
    for (_, _, _, kind, event_id), props in speaks:
        title = graph.nodes[(kind, event_id)]["title"]
        assert props["rationale"] == (f"[fixture] Listed as speaker of '{title}' on the official "
                                      "GitHub Universe session page")
        assert props["source_url"] in props["evidence_ids"]
    for props in graph.edges.values():  # no placeholder left, no nameless sentence
        assert "{from}" not in props["rationale"] and "{to}" not in props["rationale"]
        assert "'" in props["rationale"], props["rationale"]


@pytest.mark.skipif(os.getenv("CONFERGE_FALKORDB_TEST") != "1",
                    reason="set CONFERGE_FALKORDB_TEST=1 with a running FalkorDB to run")
def test_no_edge_without_evidence_id_in_falkordb():
    from falkordb import FalkorDB

    db = FalkorDB(host=os.getenv("FALKORDB_HOST", "127.0.0.1"),
                  port=int(os.getenv("FALKORDB_PORT", "6379")),
                  password=os.getenv("FALKORDB_PASSWORD") or None)
    graph = db.select_graph(os.getenv("CONFERGE_TEST_GRAPH", "conferge_w08_pytest"))
    try:
        graph.delete()
    except Exception:  # noqa: BLE001 - absent graph
        pass
    try:
        ingest_bundle(GraphStore(graph), _demo_bundle())
        rows = graph.ro_query(
            "MATCH ()-[r]->() RETURN count(r), sum(CASE WHEN r.evidence_ids IS NULL OR "
            "size(r.evidence_ids) = 0 OR r.rationale IS NULL THEN 1 ELSE 0 END)").result_set
        total, missing = rows[0]
        assert total > 1000 and missing == 0
    finally:
        graph.delete()


def test_edge_why_keeps_path_order_rationale_and_ids():
    from conferge.graph.ranking import edge_why

    path = {"nodes": [], "edges": [
        {"source": "g1", "target": "t1", "type": "ABOUT",
         "props": {"rationale": "Topic stated by the user in this goal",
                   "evidence_ids": ["record:Goal:g1"]}},
        {"source": "p1", "target": "e1", "type": "SPEAKS_AT", "props": {}}]}
    assert edge_why(path) == [
        {"edge": "ABOUT", "source": "g1", "target": "t1",
         "rationale": "Topic stated by the user in this goal", "evidence_ids": ["record:Goal:g1"]},
        {"edge": "SPEAKS_AT", "source": "p1", "target": "e1", "rationale": None,
         "evidence_ids": []}]
    assert edge_why(None) == []
