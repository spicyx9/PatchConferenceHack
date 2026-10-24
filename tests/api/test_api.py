"""Offline TestClient tests for every w12 route, on the labelled fixture."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from conferge.api import logic
from conferge.api.app import create_app
from conferge.api.data import FIXTURE_PATH, load_fixture
from conferge.api.providers import ProviderStatus, Providers
from conferge.core.schemas import AgentResult, Opportunity

DEMO_TEXT = (
    "Fondateur d'un outil dev IA, je vais à GitHub Universe pour rencontrer des "
    "investisseurs seed, des fondateurs d'agents IA et des PM Copilot."
)


@pytest.fixture()
def client() -> TestClient:
    return TestClient(create_app(found=Providers(), graph_probe=False))


def test_fixture_is_labelled_and_fictional() -> None:
    raw = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    assert raw["_meta"]["source_mode"] == "fixture"
    data = load_fixture()
    for record in [*data.events, *data.people, *data.stays, *data.flights]:
        assert record.evidence and all(e.source_mode == "fixture" for e in record.evidence)
    assert all("fictional" in p.name.lower() for p in data.people)
    assert all("[FIXTURE]" in e.title for e in data.events)
    # no invented prices or flight times
    assert all(s.total_price is None for s in data.stays)
    assert all(f.total_price is None for f in data.flights)
    assert all(
        seg.departure_at is None for f in data.flights for sl in f.slices for seg in sl.segments
    )
    assert all(e.start_at is None or e.start_at.tzinfo is not None for e in data.events)


def test_health(client: TestClient) -> None:
    for path in ("/health", "/api/v1/health"):
        body = client.get(path).json()
        assert body["status"] == "ok"
        assert body["graph_up"] is False
        assert "fastapi" in body["versions"]


def test_parse_demo_goal_weights() -> None:
    goals = logic.parse_goals(DEMO_TEXT)
    assert [(g.id, g.priority) for g in goals] == [
        ("goal-seed-investors", 0.45), ("goal-agent-founders", 0.35), ("goal-copilot-pm", 0.2),
    ]


def test_goal_demo_returns_people_and_two_day_plan(client: TestClient) -> None:
    res = client.post("/api/v1/goal", json={"text": DEMO_TEXT, "user_id": "demo-user"})
    assert res.status_code == 200
    body = res.json()
    assert body["data_source"] == "fixture"
    assert body["status"] == "degraded"
    assert len(body["people"]) >= 5
    days = [d["day"] for d in body["plan"]["days"] if d["items"]]
    assert {"2026-10-28", "2026-10-29"} <= set(days)
    assert body["plan"]["conflicts"], "demo needs an anti-FOMO conflict on the 28th evening"
    conflict = body["plan"]["conflicts"][0]
    assert conflict["day"] == "2026-10-28" and conflict["verdict"]
    assert body["computed_by"] == "api-fallback"
    assert any("planner agent not available" in w for w in body["warnings"])


def test_goal_rejects_unknown_conference_and_empty_goal(client: TestClient) -> None:
    assert client.post("/api/v1/goal", json={"text": "x", "conference_id": "nope"}).status_code == 404
    assert client.post("/api/v1/goal", json={"text": "just sightseeing"}).status_code == 422


@pytest.mark.parametrize("path", [
    "/api/v1/plan", "/api/v1/people", "/api/v1/events", "/api/v1/sessions", "/api/v1/stays",
    "/api/v1/flights", "/api/v1/travel", "/api/v1/travel/map", "/api/v1/graph",
    "/api/v1/scenarios", "/api/v1/roi", "/api/v1/sources", "/api/v1/conference",
])
def test_every_get_route_is_labelled_fixture(client: TestClient, path: str) -> None:
    res = client.get(path)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["data_source"] == "fixture"
    assert body["data_source"] != "live"
    assert body["collected_at"]
    assert any(w.startswith("FIXTURE") for w in body["warnings"])


def test_no_record_claims_live(client: TestClient) -> None:
    for path in ("/api/v1/events", "/api/v1/graph", "/api/v1/stays", "/api/v1/plan"):
        text = client.get(path).text
        assert '"source_mode":"live"' not in text
        assert '"data_source":"live"' not in text


def test_events_filters(client: TestClient) -> None:
    day = client.get("/api/v1/events", params={"day": "2026-10-28"}).json()["items"]
    assert day and all(e["start_at"].startswith("2026-10-28") for e in day)
    parties = client.get("/api/v1/events", params={"type": "party"}).json()["items"]
    assert [e["event_type"] for e in parties] == ["party"]
    high = client.get("/api/v1/events", params={"min_score": 60}).json()["items"]
    assert all(e["score"] >= 60 for e in high)
    sessions = client.get("/api/v1/sessions").json()["items"]
    assert sessions and all(e["event_type"] == "session" for e in sessions)


def test_stays_and_flights_keep_unknown_prices_null(client: TestClient) -> None:
    stays = client.get("/api/v1/stays").json()["items"]
    assert all(s["total_price"] is None and s["price_status"] == "unknown" for s in stays)
    assert all(s["distance_is_straight_line_estimate"] for s in stays)
    flights = client.get("/api/v1/flights").json()["items"]
    assert all(f["total_price"] is None for f in flights)
    travel = client.get("/api/v1/travel").json()
    assert travel["budget"]["remaining_usd"] is None
    assert travel["proposals"]
    roi = client.get("/api/v1/roi").json()
    assert roi["spend_usd"] is None and roi["meetings"] == 0


def test_travel_map(client: TestClient) -> None:
    body = client.get("/api/v1/travel/map").json()
    kinds = {m["kind"] for m in body["markers"]}
    assert {"conference", "event", "stay"} <= kinds
    assert body["polylines"]


def test_graph_and_path(client: TestClient) -> None:
    graph = client.get("/api/v1/graph").json()
    assert graph["backend"] == "api-fallback"
    assert len(graph["nodes"]) <= 400
    ids = {n["id"] for n in graph["nodes"]}
    assert all(e["source"] in ids and e["target"] in ids for e in graph["edges"])
    assert all({"evidence_source", "confidence", "observed_at"} <= set(e) for e in graph["edges"])
    people_only = client.get("/api/v1/graph", params={"type": "Person"}).json()
    assert {n["type"] for n in people_only["nodes"]} <= {"Person", "User"}
    assert len(client.get("/api/v1/graph", params={"limit": 5}).json()["nodes"]) == 5
    path = client.get("/api/v1/graph/path", params={"person": "per-fx-07"}).json()
    assert path["node_ids"][0] == "user:demo-user" and path["node_ids"][-1] == "per-fx-07"
    assert path["hops"] >= 2
    assert client.get("/api/v1/graph/path", params={"person": "nobody"}).status_code == 404


def test_met_changes_ranking_and_roi(client: TestClient) -> None:
    before = client.get("/api/v1/people").json()["items"]
    top = before[0]["person"]["id"]
    res = client.post("/api/v1/met", json={"person_id": top, "note": "talked about seed"})
    assert res.status_code == 200 and res.json()["persisted"] == "memory"
    after = client.get("/api/v1/people", params={"limit": 50}).json()["items"]
    assert after[0]["person"]["id"] != top
    met_card = next(c for c in after if c["person"]["id"] == top)
    assert met_card["met"] and met_card["met_note"] == "talked about seed"
    assert client.get("/api/v1/roi").json()["meetings"] == 1
    graph = client.get("/api/v1/graph").json()
    assert any(e["type"] == "MET" and e["target"] == top for e in graph["edges"])
    assert client.post("/api/v1/met", json={"person_id": "nobody"}).status_code == 404


def test_attended_and_skipped(client: TestClient) -> None:
    plan = client.post("/api/v1/skipped", json={"event_id": "evt-fx-agents-founders-night"}).json()
    planned = {i["event_id"] for d in plan["plan"]["days"] for i in d["items"]}
    assert "evt-fx-agents-founders-night" not in planned
    assert "evt-fx-devtools-happy-hour" in planned
    plan = client.post("/api/v1/attended", json={"event_id": "evt-fx-agents-founders-night"}).json()
    items = [i for d in plan["plan"]["days"] for i in d["items"]]
    assert any(i["event_id"] == "evt-fx-agents-founders-night" and i["attended"] for i in items)
    assert client.post("/api/v1/attended", json={"event_id": "nope"}).status_code == 404


def test_simulate_change_and_reset(client: TestClient) -> None:
    scenarios = client.get("/api/v1/scenarios").json()["items"]
    assert {s["id"] for s in scenarios} >= {"sold-out-founders-night"}
    res = client.post("/api/v1/simulate-change", json={"scenario_id": "sold-out-founders-night"})
    body = res.json()
    assert [r["event_id"] for r in body["diff"]["removed"]] == ["evt-fx-agents-founders-night"]
    assert [a["event_id"] for a in body["diff"]["added"]] == ["evt-fx-devtools-happy-hour"]
    assert any("simulated change" in w for w in body["warnings"])
    moved = client.post("/api/v1/simulate-change", json={"scenario_id": "workshop-rescheduled"}).json()
    assert moved["diff"]["changed"][0]["event_id"] == "evt-fx-mcp-workshop"
    assert client.post("/api/v1/simulate-change", json={"scenario_id": "x"}).status_code == 404
    reset = client.post("/api/v1/reset").json()
    planned = {i["event_id"] for d in reset["plan"]["days"] for i in d["items"]}
    assert "evt-fx-agents-founders-night" in planned


def test_proposal_accept(client: TestClient) -> None:
    proposal = client.get("/api/v1/travel").json()["proposals"][0]
    res = client.post("/api/v1/proposal/accept", json={"proposal_id": proposal["id"]}).json()
    assert next(p for p in res["proposals"] if p["id"] == proposal["id"])["accepted"] is True
    assert client.post("/api/v1/proposal/accept", json={"proposal_id": "x"}).status_code == 404


def test_injected_planner_agent_is_used() -> None:
    class FakePlanner:
        async def run(self, ctx):  # type: ignore[no-untyped-def]
            assert ctx.data_mode == "fixture"
            return AgentResult(
                agent="planner-test", source_mode="fixture", status="ok",
                opportunities=[Opportunity(
                    id="opp-x", title="Agent pick", goal_ids=[ctx.goals[0].id],
                    person_ids=[ctx.people[0].id], score=99, rationale="from agent",
                )],
            )

    found = Providers(agents={"planner": FakePlanner()},
                      statuses=[ProviderStatus("planner", True, "test")])
    client = TestClient(create_app(found=found, graph_probe=False))
    body = client.post("/api/v1/goal", json={"text": DEMO_TEXT}).json()
    assert body["computed_by"] == "planner-test"
    assert body["people"][0]["title"] == "Agent pick"
    assert not any("planner agent not available" in w for w in body["warnings"])


def test_failing_planner_degrades_visibly() -> None:
    class Broken:
        async def run(self, ctx):  # type: ignore[no-untyped-def]
            raise RuntimeError("boom")

    client = TestClient(create_app(found=Providers(agents={"planner": Broken()}), graph_probe=False))
    res = client.post("/api/v1/goal", json={"text": DEMO_TEXT})
    assert res.status_code == 200
    body = res.json()
    assert body["computed_by"] == "api-fallback" and len(body["people"]) >= 5
    assert any("planner agent error RuntimeError" in w for w in body["warnings"])


def test_index_served_when_static_exists(client: TestClient) -> None:
    static = Path(__file__).resolve().parents[2] / "static" / "index.html"
    res = client.get("/")
    if static.exists():
        assert res.status_code == 200 and "text/html" in res.headers["content-type"]
    else:
        assert res.status_code == 404
