"""Risk 3 of the wiring audit: a 200 must not hide a failure or overwrite the envelope status."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from fastapi.testclient import TestClient

from conferge.api import providers
from conferge.api.app import create_app
from conferge.api.providers import Providers
from conferge.core.schemas import AgentResult
from conferge.core.store import GraphStore


def _offline() -> TestClient:
    return TestClient(create_app(found=Providers(), graph_probe=False))


def test_antifomo_status_is_the_envelope_status_not_the_agent_status() -> None:
    class FakeAntifomo:
        async def run(self, ctx):  # type: ignore[no-untyped-def]
            return AgentResult(agent="antifomo-test", source_mode="fixture", status="ok",
                               decisions=[])

    client = TestClient(create_app(found=Providers(agents={"antifomo": FakeAntifomo()}),
                                   graph_probe=False))
    body = client.get("/api/v1/antifomo").json()
    # Offline: events + people are "degraded_no_graph"; the agent's "ok" must not hide it.
    assert body["data_source"] == "degraded_no_graph" and body["status"] == "degraded"
    assert body["computed_by"] == "antifomo-test" and body["agent_status"] == "ok"


def test_followup_serves_draft_status_and_keeps_the_envelope_status() -> None:
    client = _offline()
    top = client.get("/api/v1/people?limit=1").json()["items"][0]["person"]["id"]
    client.post("/api/v1/met", json={"person_id": top, "note": "hallway"})
    body = client.get("/api/v1/followup", params={"person": top}).json()
    assert body["draft_status"] == "draft" and body["sent"] is False
    assert body["status"] in {"ok", "degraded", "failed"}  # envelope status, not "draft"


def test_met_and_skipped_warn_when_memory_did_not_reach_falkordb() -> None:
    client = _offline()
    top = client.get("/api/v1/people?limit=1").json()["items"][0]["person"]["id"]
    met = client.post("/api/v1/met", json={"person_id": top}).json()
    assert met["persisted"] == "memory"
    assert any("not written to FalkorDB" in w for w in met["warnings"])
    event = client.get("/api/v1/events").json()["items"][0]["id"]
    skipped = client.post("/api/v1/skipped", json={"event_id": event, "reason": "conflict"}).json()
    assert skipped["persisted"] == "memory"
    assert any("not written to FalkorDB" in w for w in skipped["warnings"])


class _BrokenWriteGraph:
    """Reads answer (empty), the planner's write raises: the plan is served, visibly unshared."""

    def query(self, q: str, params: dict[str, Any] | None = None) -> SimpleNamespace:
        if "MERGE" in q or "CREATE" in q or "SET" in q:
            raise RuntimeError("write refused")
        return SimpleNamespace(result_set=[])

    ro_query = query


def test_plan_graph_write_error_becomes_a_warning(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(providers, "connect_store", lambda: GraphStore(_BrokenWriteGraph()))
    client = TestClient(create_app(found=Providers(), graph_probe=True))
    body = client.get("/api/v1/plan").json()
    assert body["plan_graph"] == {"error": "RuntimeError"}
    assert any(w.startswith("plan not written to FalkorDB: RuntimeError") for w in body["warnings"])
