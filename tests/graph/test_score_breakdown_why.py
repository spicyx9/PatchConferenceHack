"""Graph score breakdown (noisy-OR split), grade, and the deterministic why answer."""

from __future__ import annotations

import re
from types import SimpleNamespace
from typing import Any

import pytest
from falkordb import Edge, Node, Path

from conferge.core.schemas import Goal
from conferge.graph import queries as q
from conferge.graph.ranking import rank_people
from conferge.graph.why import why_person

CATALOG = "https://example.org/sessioncatalog"
LUMA = "https://lu.ma/agents-night"
LINKEDIN = "https://www.linkedin.com/in/alice-example/"


class FakeGraph:
    def __init__(self, responses: list[tuple[str, list[list[Any]]]]) -> None:
        self.responses = responses

    def ro_query(self, query: str, params: dict[str, Any] | None = None) -> Any:
        for constant, rows in self.responses:
            if query is constant:
                return SimpleNamespace(result_set=rows)
        return SimpleNamespace(result_set=[])


_IDS = iter(range(1, 10_000))


def node(label: str, node_id: str, **props: Any) -> Node:
    return Node(node_id=next(_IDS), labels=label, properties={"id": node_id, **props})


def edge(a: Node, rel: str, b: Node, **props: Any) -> Edge:
    return Edge(a.id, rel, b.id, properties=props)


GOAL = node("Goal", "g1", description="Meet AI founders")
TOPIC = node("Topic", "topic:ai-agents", name="AI agents")
TALK = node("Event", "e-talk", title="Talk")
NIGHT = node("Event", "e-night", title="Night")
ALICE = node("Person", "p-alice", name="Alice", title="Founder")
ACME = node("Company", "c-acme", name="Acme")

GOAL_ABOUT = edge(GOAL, "ABOUT", TOPIC, rationale="Topic stated by the user in this goal",
                  evidence_ids=["record:Goal:g1"], confidence=1.0)


def _speaker_path() -> Path:
    return Path([GOAL, TOPIC, TALK, ALICE], [
        GOAL_ABOUT,
        edge(TALK, "ABOUT", TOPIC, source="rainfocus", source_url=CATALOG, confidence=1.0,
             rationale="Topic tagged on the official session page", evidence_ids=[CATALOG]),
        edge(ALICE, "SPEAKS_AT", TALK, source="rainfocus", source_url=CATALOG, confidence=1.0,
             rationale="Listed as speaker on the official session page", evidence_ids=[CATALOG])])


def _host_path() -> Path:
    return Path([GOAL, TOPIC, NIGHT, ALICE], [
        GOAL_ABOUT,
        edge(NIGHT, "ABOUT", TOPIC, source="luma", source_url=LUMA, confidence=0.6,
             rationale="Topic tagged on the Luma event page", evidence_ids=[LUMA]),
        edge(ALICE, "HOSTS", NIGHT, source="luma", source_url=LUMA, confidence=1.0,
             rationale="Listed as organizer on the Luma event page", evidence_ids=[LUMA])])


def _company_path() -> Path:
    return Path([GOAL, TOPIC, ACME, ALICE], [
        GOAL_ABOUT,
        edge(ACME, "ABOUT", TOPIC, source="rainfocus", source_url=CATALOG, confidence=1.0,
             rationale="Topic tagged on the official session page", evidence_ids=[CATALOG]),
        edge(ALICE, "WORKS_AT", ACME, source="rainfocus", source_url=CATALOG, confidence=1.0,
             linkedin_snapshot_id="sd_example", linkedin_source_url=LINKEDIN,
             rationale="WORKS_AT corroborated by LinkedIn profile collected via Bright Data",
             evidence_ids=[CATALOG, LINKEDIN, "sd_example"])])


def _ranking_graph() -> FakeGraph:
    return FakeGraph([
        (q.Q_GOAL, [[1.0, "Meet AI founders"]]),
        (q.Q_PEOPLE_VIA_SPEAKER, [["p-alice", _speaker_path()]]),
        (q.Q_PEOPLE_VIA_HOST, [["p-alice", _host_path()]]),
        (q.Q_PEOPLE_BY_ROLE, [["p-alice", ["founder"]]]),
        (q.Q_PERSON_NAMES, [["p-alice", "Alice", "Founder", ["founder"]]]),
    ])


# -- noisy-OR split ----------------------------------------------------------------


def test_attribution_sums_to_noisy_or_and_routes_parts():
    contribs = [("a", "speaker", 0.9), ("a", "topic", 0.4), ("b", "host", 0.6),
                ("person_record:roles", "role", 0.6)]
    parts = q.attribute_by_source(contribs)
    assert sum(parts.values()) == pytest.approx(
        q.combine_by_source([(s, v) for s, _, v in contribs]))
    assert parts["presence"] == pytest.approx(0.9)  # strongest source, a speaker path
    assert parts["corroboration"] == pytest.approx(0.6 * 0.1 + 0.6 * 0.1 * 0.4)
    assert "goal_fit" not in parts
    assert q.attribute_by_source([("x", "topic", 0.4)]) == {"goal_fit": pytest.approx(0.4)}


def test_people_for_goal_rows_carry_parts_matching_score():
    row = q.people_for_goal(_ranking_graph(), "demo-user", "g1")["rows"][0]
    assert sum(row["parts"].values()) == pytest.approx(row["score"], abs=1e-4)


# -- rank_people: breakdown and grade ------------------------------------------------


def test_rank_people_breakdown_sums_to_score_and_grades():
    goals = [Goal(id="g1", description="Meet AI founders", priority=1.0)]
    opp = rank_people(_ranking_graph(), "demo-user", goals)[0]
    parts = opp.score_breakdown
    assert set(parts) == {"goal_fit", "presence", "identity", "corroboration", "graph"}
    assert round(sum(parts.values()), 1) == opp.score
    assert parts["presence"] == 100.0 * 1.0 and parts["identity"] == 0 and parts["graph"] == 0
    assert opp.grade == "A"


@pytest.mark.parametrize(("priority", "grade"), [(0.5, "C"), (0.66, "B"), (0.3, "D")])
def test_rank_people_grade_thresholds(priority, grade):
    graph = FakeGraph([(q.Q_GOAL, [[priority, "g"]]),
                       (q.Q_PEOPLE_VIA_SPEAKER, [["p-alice", _speaker_path()]]),
                       (q.Q_PERSON_NAMES, [["p-alice", "Alice", None, []]])])
    opp = rank_people(graph, "demo-user", [Goal(id="g1", description="g", priority=priority)])[0]
    assert opp.score == round(100 * priority, 1)
    assert opp.grade == grade
    assert round(sum(opp.score_breakdown.values()), 1) == opp.score


# -- why ------------------------------------------------------------------------------


def _why_graph(*paths: Path, query: str = q.Q_PATH_SPEAKER) -> FakeGraph:
    return FakeGraph([(query, [["g1", len(p.edges()), p] for p in paths])])


def test_why_cites_only_evidence_ids_of_the_path_edges():
    paths = (_speaker_path(), _company_path())
    why = why_person(_why_graph(*paths), "demo-user", "p-alice")
    on_edges = {i for p in paths for e in p.edges() for i in e.properties["evidence_ids"]}
    cited = set(re.findall(r"\[ev:([^\]]+)\]", why["answer"]))
    listed = {ev["evidence_id"] for ev in why["evidence"]}
    assert cited == listed and cited <= on_edges
    assert why["sentences"][0] == "Topic stated by the user in this goal. [ev:record:Goal:g1]"
    assert why["sentences"].count(why["sentences"][0]) == 1  # shared goal edge said once
    assert ("Listed as speaker on the official session page. [ev:%s]" % CATALOG
            in why["sentences"])


def test_why_evidence_resolves_urls_and_snapshot_ids():
    why = why_person(_why_graph(_company_path(), query=q.Q_PATH_COMPANY_TOPIC),
                     "demo-user", "p-alice")
    urls = {ev["evidence_id"]: ev["source_url"] for ev in why["evidence"]}
    assert urls == {"record:Goal:g1": None, CATALOG: CATALOG, LINKEDIN: LINKEDIN,
                    "sd_example": LINKEDIN}
    assert why["signature"] == "company_topic"


def test_why_skips_edges_without_rationale_and_handles_no_path():
    bare = Path([ALICE, TALK], [edge(ALICE, "SPEAKS_AT", TALK)])
    assert why_person(_why_graph(bare), "demo-user", "p-alice")["sentences"] == []
    empty = why_person(FakeGraph([]), "demo-user", "p-x")
    assert empty["answer"] is None and empty["evidence"] == [] and empty["paths"] == 0
