"""Offline tests for read-only traversals using real falkordb Node/Edge/Path objects."""

from __future__ import annotations

import re
from pathlib import Path as FsPath
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest
from falkordb import Edge, Node, Path

import conferge.graph as graph_pkg
from conferge.core.store import GraphStore
from conferge.graph import queries as q
from conferge.graph.queries import conflicts, people_for_goal, run_read


class FakeGraph:
    """Answers ``ro_query`` by identity of the query constant."""

    def __init__(self, responses: list[tuple[str, list[list[Any]]]]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def ro_query(self, query: str, params: dict[str, Any] | None = None) -> Any:
        self.calls.append((query, params or {}))
        for constant, rows in self.responses:
            if query is constant:
                return SimpleNamespace(result_set=rows)
        return SimpleNamespace(result_set=[])

    def query(self, *_: Any, **__: Any) -> Any:  # pragma: no cover - must not be used
        raise AssertionError("write-capable query() used where ro_query is available")


_COUNTER = iter(range(1, 10_000))


def node(label: str, node_id: str, **props: Any) -> Node:
    return Node(node_id=next(_COUNTER), labels=label, properties={"id": node_id, **props})


def path(*items: Any) -> Path:
    """path(n0, "REL", n1, ...) with direction given by arrow: "REL>" n_i->n_{i+1},
    "<REL" n_{i+1}->n_i."""
    nodes = list(items[0::2])
    edges = []
    for i, rel in enumerate(items[1::2]):
        a, b = nodes[i], nodes[i + 1]
        if rel.startswith("<"):
            edges.append(Edge(b.id, rel[1:], a.id, properties={}))
        else:
            edges.append(Edge(a.id, rel.rstrip(">"), b.id, properties={}))
    return Path(nodes, edges)


GOAL = node("Goal", "g1", description="Meet AI founders")
TOPIC = node("Topic", "topic:ai-agents", name="AI agents")
TALK = node("Event", "e-talk", title="Talk")
NIGHT = node("Event", "e-night", title="Night")
ALICE = node("Person", "p-alice", name="Alice")
BOB = node("Person", "p-bob", name="Bob")
CAROL = node("Person", "p-carol", name="Carol")
MEETING = node("Meeting", "memory:demo-user:met:p-carol", kind="MET")

ALICE_SPEAKER = path(GOAL, "ABOUT>", TOPIC, "<ABOUT", TALK, "<SPEAKS_AT", ALICE)
ALICE_TOPIC = path(GOAL, "ABOUT>", TOPIC, "<ABOUT", ALICE)
BOB_TOPIC = path(GOAL, "ABOUT>", TOPIC, "<ABOUT", BOB)
CAROL_ATTEND = path(GOAL, "ABOUT>", TOPIC, "<ABOUT", NIGHT, "<ATTENDS_CONFIRMED", CAROL)
CAROL_MET = path(MEETING, "MET>", CAROL)


def _goal_graph(include_met_rows: bool = True) -> FakeGraph:
    met_rows = [["p-carol", "Carol", "MET", "2026-10-28T09:00:00+00:00", CAROL_MET],
                ["p-bob", "Bob", "SKIPPED", "2026-10-28T09:00:00+00:00", path(MEETING, "INVOLVES>", BOB)]]
    return FakeGraph([
        (q.Q_GOAL, [[0.5, "Meet AI founders"]]),
        (q.Q_PEOPLE_MET_BEFORE, met_rows if include_met_rows else []),
        # Duplicate path for alice must be counted once.
        (q.Q_PEOPLE_VIA_SPEAKER, [["p-alice", ALICE_SPEAKER], ["p-alice", ALICE_SPEAKER]]),
        (q.Q_PEOPLE_VIA_ATTENDANCE, [["p-carol", CAROL_ATTEND]]),
        (q.Q_PEOPLE_VIA_TOPIC, [["p-alice", ALICE_TOPIC], ["p-bob", BOB_TOPIC]]),
        (q.Q_PEOPLE_BY_ROLE, [["p-frank", ["founder"]]]),
        (q.Q_PERSON_NAMES, [["p-alice", "Alice", "Founder", ["founder"]],
                            ["p-bob", "Bob", None, ["engineer"]],
                            ["p-frank", "Frank", "Founder", ["founder"]],
                            ["p-carol", "Carol", "Partner", ["investor"]]]),
    ])


def test_people_for_goal_aggregates_excludes_and_ranks():
    graph = _goal_graph()
    result = people_for_goal(graph, "demo-user", "g1")
    rows = result["rows"]
    assert [r["person_id"] for r in rows] == ["p-frank", "p-alice", "p-bob"]
    by_id = {r["person_id"]: r for r in rows}
    # alice: speaker and topic paths carry no provenance, so they share the "unknown" root
    # source (max, not sum) and no confidence (0.5): max(1.0, 0.4) * 0.5, times priority 0.5
    assert by_id["p-alice"]["score"] == pytest.approx(0.25)
    assert by_id["p-alice"]["unknown_confidence"] is True
    assert by_id["p-alice"]["path_count"] == 2
    assert by_id["p-alice"]["reasons"] == ["speaker", "topic"]
    assert by_id["p-alice"]["shortest_hops"] == 2
    assert by_id["p-alice"]["name"] == "Alice"
    assert by_id["p-frank"]["score"] == pytest.approx(0.3)
    assert by_id["p-frank"]["path_count"] == 0
    assert by_id["p-bob"]["score"] == pytest.approx(0.1)  # SKIPPED does not exclude
    assert "p-carol" not in by_id  # MET memory excludes

    paths = result["paths"]
    assert len(paths) == 3  # alice speaker + alice topic + bob topic
    first = paths[0]  # frank has no path; alice strongest evidence (speaker) first
    assert [n["id"] for n in first["nodes"]] == ["g1", "topic:ai-agents", "e-talk", "p-alice"]
    for p in paths:
        for n in p["nodes"]:
            assert set(n) == {"id", "label", "props"}
            assert "id" not in n["props"]
        for e in p["edges"]:
            assert {"source", "target", "type"} <= set(e)
    assert first["nodes"][-1]["label"] == "Person"
    assert first["edges"][-1] == {"source": "p-alice", "target": "e-talk", "type": "SPEAKS_AT",
                                  "props": {}, "evidence_source": None, "confidence": None,
                                  "observed_at": None}
    assert first["edges"][0]["source"] == "g1" and first["edges"][0]["target"] == "topic:ai-agents"


def test_people_for_goal_include_met():
    result = people_for_goal(_goal_graph(), "demo-user", "g1", include_met=True)
    assert "p-carol" in {r["person_id"] for r in result["rows"]}


def test_people_for_goal_contacted_excluded():
    graph = _goal_graph(include_met_rows=False)
    graph.responses.insert(0, (q.Q_PEOPLE_MET_BEFORE, [
        ["p-alice", "Alice", "CONTACTED", "2026-10-28T09:00:00+00:00",
         path(MEETING, "INVOLVES>", ALICE)]]))
    result = people_for_goal(graph, "demo-user", "g1")
    ids = [r["person_id"] for r in result["rows"]]
    assert "p-alice" not in ids
    assert all(p["nodes"][-1]["id"] != "p-alice" for p in result["paths"])


def test_people_for_goal_unknown_goal_empty():
    graph = FakeGraph([(q.Q_PEOPLE_VIA_SPEAKER, [["p-alice", ALICE_SPEAKER]])])
    assert people_for_goal(graph, "demo-user", "nope") == {"rows": [], "paths": []}


def test_queries_bind_user_and_goal_params():
    graph = _goal_graph()
    people_for_goal(graph, "demo-user", "g1")
    for query, params in graph.calls:
        if query is q.Q_PEOPLE_VIA_SPEAKER:
            assert params["goal_id"] == "g1" and params["user_id"] == "demo-user"


# -- conflicts --------------------------------------------------------------------


def test_conflicts_distance_and_unverifiable():
    graph = FakeGraph([
        (q.Q_CONFLICTS, [
            ["e-a", "A", "s", "e", "e-b", "B", "s", "e",
             "Fort Mason", 37.806, -122.432, "Hall", 37.803, -122.437],
            ["e-c", "C", "s", "e", "e-d", "D", "s", "e",
             "Somewhere", None, None, "Hall", 37.803, -122.437],
        ]),
        (q.Q_UNTIMED_EVENTS, [["e-x", "Untimed"]]),
    ])
    rows = conflicts(graph, "conf")["rows"]
    overlaps = [r for r in rows if r["kind"] == "overlap"]
    assert len(overlaps) == 2
    distance = overlaps[0]["distance_m"]
    assert isinstance(distance, int)
    assert 540 <= distance <= 565  # ~552 m between the two points
    assert overlaps[0]["a"]["venue"] == "Fort Mason"
    assert overlaps[1]["distance_m"] is None
    unverifiable = [r for r in rows if r["kind"] == "unverifiable"]
    assert unverifiable == [{"kind": "unverifiable", "a": {"id": "e-x", "title": "Untimed"},
                             "reason": "missing start or end time"}]
    assert all(params == {"conference_id": "conf"} for _, params in graph.calls)


# -- run_read -----------------------------------------------------------------------


def test_run_read_prefers_ro_query():
    graph = Mock()
    graph.ro_query.return_value = SimpleNamespace(result_set=[[1]])
    assert run_read(graph, "MATCH (n) RETURN n", {"x": 1}) == [[1]]
    graph.ro_query.assert_called_once_with("MATCH (n) RETURN n", params={"x": 1})
    graph.query.assert_not_called()


def test_run_read_falls_back_to_query_and_unwraps_store():
    graph = Mock(spec=["query"])
    graph.query.return_value = SimpleNamespace(result_set=None)
    assert run_read(GraphStore(graph), "MATCH (n) RETURN n") == []
    graph.query.assert_called_once_with("MATCH (n) RETURN n", params={})


# -- static safety ---------------------------------------------------------------------

_WRITE_RE = re.compile(r"\b(MERGE|CREATE|SET|DELETE|REMOVE|DETACH)\b", re.IGNORECASE)


def test_read_queries_registry_complete():
    constants = {name for name in dir(q) if name.startswith("Q_")}
    assert constants == set(q.READ_QUERIES)
    assert len(constants) >= 20


@pytest.mark.parametrize("name", sorted(q.READ_QUERIES))
def test_read_queries_have_no_write_keywords(name):
    query = q.READ_QUERIES[name]
    assert not _WRITE_RE.search(query), f"{name}: {query}"


@pytest.mark.parametrize("name", sorted(q.READ_QUERIES))
def test_read_queries_use_params(name):
    query = q.READ_QUERIES[name]
    if name in {"Q_NODE_COUNTS", "Q_EDGE_COUNTS"}:  # take no input at all
        assert "$" not in query
        return
    assert "$" in query, name
    # Inline property maps only bind parameters, never literal values.
    for prop_map in re.findall(r"\{([^}]*)\}", query):
        for _, value in re.findall(r"(\w+):\s*([^,]+)", prop_map):
            assert value.strip().startswith("$"), f"{name}: {prop_map}"


def test_graph_package_never_builds_merge_cypher():
    package_dir = FsPath(graph_pkg.__file__).parent
    files = sorted(package_dir.glob("*.py"))
    assert files
    for source in files:
        assert "MERGE (" not in source.read_text(encoding="utf-8"), source.name


# -- evidence scoring: unknown confidence, root-source grouping, noisy-OR ----------


def _sourced(src: str, url: str, *items: Any) -> Path:
    p = path(*items)
    for e in p.edges():
        e.properties = {"source": src, "source_url": url, "confidence": 1.0}
    return p


def test_missing_edge_confidence_counts_half_and_flags_path():
    serialized = q.serialize_path(ALICE_SPEAKER)
    assert q._path_confidence(serialized) == pytest.approx(0.5)
    assert serialized["flags"] == ["unknown_confidence"]


def test_three_paths_from_one_source_count_once():
    t2, t3 = node("Event", "e-2", title="T2"), node("Event", "e-3", title="T3")
    same = [_sourced("rainfocus", "https://cat", GOAL, "ABOUT>", TOPIC, "<ABOUT", ev, "<SPEAKS_AT", ALICE)
            for ev in (TALK, t2, t3)]
    graph = FakeGraph([(q.Q_GOAL, [[1.0, "g"]]),
                       (q.Q_PEOPLE_VIA_SPEAKER, [["p-alice", p] for p in same])])
    row = people_for_goal(graph, "demo-user", "g1")["rows"][0]
    assert row["path_count"] == 3
    assert row["score"] == pytest.approx(1.0 * 1.0)  # one contribution, not 3.0
    assert row["sources"] == ["rainfocus|https://cat"]
    assert row["unknown_confidence"] is False


def test_independent_sources_noisy_or_with_diminishing_returns():
    assert q.combine_by_source([("a", 0.4), ("a", 0.3), ("a", 0.4)]) == pytest.approx(0.4)
    two = q.combine_by_source([("a", 0.4), ("b", 0.4)])
    three = q.combine_by_source([("a", 0.4), ("b", 0.4), ("c", 0.4)])
    assert two == pytest.approx(1 - 0.6 * 0.6)
    assert 0.4 < two < three < 1.0
    assert (two - 0.4) > (three - two)  # each extra source adds less


# -- explicit path signatures ------------------------------------------------------


def test_path_user_to_person_tries_signatures_in_order():
    hosted = path(GOAL, "ABOUT>", TOPIC, "<ABOUT", NIGHT, "<HOSTS", BOB)
    graph = FakeGraph([(q.Q_PATH_HOST, [["g1", 3, hosted]]),
                       (q.Q_PATH_OPPORTUNITY, [["g1", 2, path(GOAL, "<SERVES_GOAL", node("Opportunity", "o"), "INVOLVES>", BOB)]])])
    result = q.path_user_to_person(graph, "demo-user", "p-bob")
    assert result["rows"][0]["signature"] == "host"
    assert [c[0] for c in graph.calls][:5] == [q.Q_PATH_SPEAKER, q.Q_PATH_ATTENDEE, q.Q_PATH_HOST_COMPANY,
                                               q.Q_PATH_COMPANY_TOPIC, q.Q_PATH_HOST]
    edge = result["paths"][0]["edges"][-1]
    assert {"type", "evidence_source", "confidence", "observed_at"} <= set(edge)
    assert "shortestPath" not in "".join(query for _, query in q.PATH_SIGNATURES)


def test_path_user_to_person_without_match_is_empty():
    assert q.path_user_to_person(FakeGraph([]), "demo-user", "p-x") == {"rows": [], "paths": []}
